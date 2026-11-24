"""CPU MDX-Net (`Kim_Vocal_2.onnx`) vocal/BGM stem separator with FFmpeg mid/side fallback (Stage R3)."""
from __future__ import annotations

import gc
import logging
import subprocess
from pathlib import Path

import numpy as np

from videocreator.models_manager import get_local_model
from videocreator.paths import AppPaths, find_ffmpeg_binary
from videocreator.pipeline.ffmpeg import run_ffmpeg
from videocreator.pipeline.probe import probe_duration

logger = logging.getLogger("videocreator.pipeline.audio_sep")

_MDX_SR = 44100
_OUT_SR = 48000
_N_FFT = 6144
_HOP = 1024
_DIM_F = 3072
_DIM_T = 256


def probe_audio_channels(media_path: Path) -> int:
    cmd = [
        find_ffmpeg_binary("ffprobe"),
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=channels",
        "-of",
        "default=nw=1:nk=1",
        str(media_path),
    ]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=15,
        stdin=subprocess.DEVNULL,
        check=False,
    )
    if proc.returncode != 0 or not (proc.stdout or "").strip():
        return 0
    try:
        return max(0, int(proc.stdout.strip().splitlines()[0]))
    except ValueError:
        return 0


def _stft_stereo(wav_2ch: np.ndarray, window: np.ndarray) -> tuple[np.ndarray, int]:
    """Computes complex STFT `(2, F, T)` matching PyTorch `torch.stft(..., center=True, normalized=False)`."""
    orig_len = wav_2ch.shape[1]
    pad = _N_FFT // 2
    padded = np.pad(wav_2ch, ((0, 0), (pad, pad)), mode="reflect")
    frames_l = np.lib.stride_tricks.sliding_window_view(padded[0], _N_FFT)[::_HOP] * window
    frames_r = np.lib.stride_tricks.sliding_window_view(padded[1], _N_FFT)[::_HOP] * window
    spec_l = np.fft.rfft(frames_l, n=_N_FFT, axis=-1).T
    spec_r = np.fft.rfft(frames_r, n=_N_FFT, axis=-1).T
    return np.stack([spec_l, spec_r], axis=0), orig_len


def _istft_stereo(spec_2ch: np.ndarray, window: np.ndarray, orig_len: int) -> np.ndarray:
    """Inverse STFT `(2, F, T) -> (2, orig_len)` via COLA overlap-add."""
    n_frames = spec_2ch.shape[2]
    pad = _N_FFT // 2
    total_len = _N_FFT + (n_frames - 1) * _HOP
    out = np.zeros((2, total_len), dtype=np.float32)
    win_sq = (window * window).astype(np.float32)
    norm = np.zeros(total_len, dtype=np.float32)

    for ch in range(2):
        time_frames = np.fft.irfft(spec_2ch[ch].T, n=_N_FFT, axis=-1).astype(np.float32) * window
        for idx in range(n_frames):
            pos = idx * _HOP
            out[ch, pos : pos + _N_FFT] += time_frames[idx]
            if ch == 0:
                norm[pos : pos + _N_FFT] += win_sq

    safe_norm = np.where(norm > 1e-8, norm, 1.0)
    out /= safe_norm[None, :]
    sliced = out[:, pad : pad + orig_len]
    if sliced.shape[1] < orig_len:
        sliced = np.pad(sliced, ((0, 0), (0, orig_len - sliced.shape[1])))
    return sliced


def _run_mdx_onnx_separation(onnx_path: Path, stereo_44k: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Runs `Kim_Vocal_2.onnx` on `(2, N)` 44.1kHz stereo audio -> `(vocals_2ch, bgm_2ch)`."""
    import onnxruntime as ort

    window = np.hanning(_N_FFT + 1)[:-1].astype(np.float32)
    spec_mix, orig_len = _stft_stereo(stereo_44k, window)  # (2, 3073, T)
    total_frames = spec_mix.shape[2]

    # Pack [L.real, L.imag, R.real, R.imag] truncated to _DIM_F=3072
    packed = np.stack(
        [
            spec_mix[0, :_DIM_F, :].real,
            spec_mix[0, :_DIM_F, :].imag,
            spec_mix[1, :_DIM_F, :].real,
            spec_mix[1, :_DIM_F, :].imag,
        ],
        axis=0,
    ).astype(np.float32)

    stride = _DIM_T - 64  # 192 frames (~4.4s) step with 64-frame crossfade
    if total_frames <= _DIM_T:
        pad_t = _DIM_T - total_frames
        packed_padded = np.pad(packed, ((0, 0), (0, 0), (0, pad_t)))
        starts = [0]
    else:
        rem = (total_frames - _DIM_T) % stride
        pad_t = (stride - rem) % stride
        packed_padded = np.pad(packed, ((0, 0), (0, 0), (0, pad_t))) if pad_t else packed
        starts = list(range(0, packed_padded.shape[2] - _DIM_T + 1, stride))

    padded_t = packed_padded.shape[2]
    pred_acc = np.zeros((4, _DIM_F, padded_t), dtype=np.float32)
    weight_acc = np.zeros(padded_t, dtype=np.float32)
    chunk_w = np.hanning(_DIM_T + 2)[1:-1].astype(np.float32)

    sess_opts = ort.SessionOptions()
    sess_opts.intra_op_num_threads = 4
    sess_opts.inter_op_num_threads = 1
    sess = ort.InferenceSession(
        str(onnx_path),
        sess_options=sess_opts,
        providers=["CPUExecutionProvider"],
    )
    inp_name = sess.get_inputs()[0].name
    try:
        for st in starts:
            chunk = packed_padded[:, :, st : st + _DIM_T][None]  # (1, 4, 3072, 256)
            out_chunk = sess.run(None, {inp_name: chunk})[0][0]  # (4, 3072, 256)
            w = np.ones(_DIM_T, dtype=np.float32) if len(starts) == 1 else chunk_w
            pred_acc[:, :, st : st + _DIM_T] += out_chunk * w[None, None, :]
            weight_acc[st : st + _DIM_T] += w
    finally:
        del sess
        gc.collect()

    safe_w = np.where(weight_acc > 1e-6, weight_acc, 1.0)
    pred_vocal = (pred_acc / safe_w[None, None, :])[:, :, :total_frames]

    spec_vocal = np.zeros_like(spec_mix)
    spec_vocal[0, :_DIM_F, :] = pred_vocal[0] + 1j * pred_vocal[1]
    spec_vocal[1, :_DIM_F, :] = pred_vocal[2] + 1j * pred_vocal[3]

    vocals_44k = _istft_stereo(spec_vocal, window, orig_len)
    vocals_44k = np.clip(vocals_44k, -1.0, 1.0)
    bgm_44k = np.clip(stereo_44k - vocals_44k, -1.0, 1.0)
    return vocals_44k, bgm_44k


def separate_vocals_and_bgm_smart(
    paths: AppPaths,
    input_media: Path,
    out_dir: Path,
) -> tuple[Path, Path, bool]:
    """Separates vocals and BGM into 48kHz WAV stems. Returns `(vocal_wav, bgm_wav, used_mdx_onnx)`."""
    out_dir.mkdir(parents=True, exist_ok=True)
    vocal_wav = out_dir / "vocal.wav"
    bgm_wav = out_dir / "bgm.wav"

    channels = probe_audio_channels(input_media)
    if channels == 0:
        try:
            dur = max(0.5, probe_duration(input_media))
        except Exception:
            dur = 2.0
        for dest in (vocal_wav, bgm_wav):
            run_ffmpeg(
                [
                    "-f",
                    "lavfi",
                    "-i",
                    "anullsrc=channel_layout=mono:sample_rate=48000",
                    "-t",
                    f"{dur:.3f}",
                    "-c:a",
                    "pcm_s16le",
                    str(dest.resolve()),
                ]
            )
        return vocal_wav, bgm_wav, True

    mdx_info = get_local_model(paths, "uvr_mdx_kim_vocal2")
    if mdx_info and mdx_info.get("status") == "ready" and mdx_info.get("installed_on_disk"):
        try:
            import soundfile as sf
            import soxr

            tmp_44k = out_dir / "_mix_44k.wav"
            run_ffmpeg(
                [
                    "-i",
                    str(input_media.resolve()),
                    "-vn",
                    "-c:a",
                    "pcm_s16le",
                    "-ar",
                    str(_MDX_SR),
                    "-ac",
                    "2",
                    str(tmp_44k.resolve()),
                ]
            )
            data, sr = sf.read(str(tmp_44k), dtype="float32", always_2d=True)
            tmp_44k.unlink(missing_ok=True)
            stereo_44k = np.ascontiguousarray(data.T, dtype=np.float32)  # (2, N)

            onnx_file = Path(str(mdx_info["local_path"]))
            if onnx_file.is_dir():
                onnx_file = next(onnx_file.glob("*.onnx"))

            vocals_44k, bgm_44k = _run_mdx_onnx_separation(onnx_file, stereo_44k)
            vocal_mono_44k = 0.5 * (vocals_44k[0] + vocals_44k[1])
            vocal_48k = soxr.resample(vocal_mono_44k, sr, _OUT_SR).astype(np.float32)
            bgm_48k = soxr.resample(bgm_44k.T, sr, _OUT_SR).astype(np.float32)  # (N, 2)

            sf.write(str(vocal_wav), np.clip(vocal_48k, -1.0, 1.0), _OUT_SR, subtype="PCM_16")
            sf.write(str(bgm_wav), np.clip(bgm_48k, -1.0, 1.0), _OUT_SR, subtype="PCM_16")
            return vocal_wav, bgm_wav, True
        except Exception as exc:
            logger.warning("MDX-Net separation failed for %s; falling back to FFmpeg DSP: %s", input_media.name, exc)

    vocal_af = (
        "pan=mono|c0=0.5*c0+0.5*c1,highpass=f=120,lowpass=f=7500"
        if channels >= 2
        else "highpass=f=120,lowpass=f=7500"
    )
    run_ffmpeg(
        [
            "-i",
            str(input_media.resolve()),
            "-vn",
            "-af",
            vocal_af,
            "-c:a",
            "pcm_s16le",
            "-ar",
            "48000",
            "-ac",
            "1",
            str(vocal_wav.resolve()),
        ],
        allow_creative_filters=True,
    )
    bgm_af = (
        "pan=stereo|c0=c0-0.85*c1|c1=c1-0.85*c0,lowpass=f=4500,volume=0.8"
        if channels >= 2
        else "lowpass=f=400,volume=0.35"
    )
    run_ffmpeg(
        [
            "-i",
            str(input_media.resolve()),
            "-vn",
            "-af",
            bgm_af,
            "-c:a",
            "pcm_s16le",
            "-ar",
            "48000",
            "-ac",
            "2",
            str(bgm_wav.resolve()),
        ],
        allow_creative_filters=True,
    )
    return vocal_wav, bgm_wav, False

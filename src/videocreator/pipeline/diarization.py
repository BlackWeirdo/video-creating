"""CPU multi-speaker diarization (`3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx`) & project-scoped reference clips."""
from __future__ import annotations

import gc
import logging
from pathlib import Path
from typing import Any

import numpy as np

from videocreator.models_manager import get_local_model
from videocreator.paths import AppPaths

logger = logging.getLogger("videocreator.pipeline.diarization")

_FBANK_SR = 16000
_REF_SR = 24000
_DEFAULT_VI_VOICES: tuple[tuple[str, str, str], ...] = (
    ("edge", "vi-VN-HoaiMyNeural", "Người nói 1 (Nữ - Hoài My)"),
    ("edge", "vi-VN-NamMinhNeural", "Người nói 2 (Nam - Nam Minh)"),
    ("vieneu", "Trúc Ly", "Người nói 3 (Nữ - Trúc Ly)"),
    ("vieneu", "Minh Quân", "Người nói 4 (Nam - Minh Quân)"),
    ("vieneu", "Ái Hân", "Người nói 5 (Nữ - Ái Hân)"),
    ("vieneu", "Đức Trí", "Người nói 6 (Nam - Đức Trí)"),
)


def _compute_kaldi_fbank_80(wav_16k: np.ndarray) -> np.ndarray:
    import kaldi_native_fbank as knf

    opts = knf.FbankOptions()
    opts.frame_opts.samp_freq = _FBANK_SR
    opts.frame_opts.frame_shift_ms = 10.0
    opts.frame_opts.frame_length_ms = 25.0
    opts.frame_opts.dither = 0.0
    opts.frame_opts.snip_edges = True
    opts.frame_opts.window_type = "povey"
    opts.frame_opts.remove_dc_offset = True
    opts.frame_opts.preemph_coeff = 0.97
    opts.mel_opts.num_bins = 80

    fb = knf.OnlineFbank(opts)
    fb.accept_waveform(_FBANK_SR, wav_16k.astype(np.float32))
    fb.input_finished()
    n = fb.num_frames_ready
    if n == 0:
        raise ValueError("Audio slice too short for Kaldi fbank")
    feats = np.stack([fb.get_frame(i) for i in range(n)]).astype(np.float32)
    return feats - feats.mean(axis=0, keepdims=True)


def diarize_segments_on_cpu(
    paths: AppPaths,
    vocal_wav: Path,
    segments: list[dict[str, Any]],
    *,
    speakers_dir: Path,
    media_root: Path,
    max_speakers: int = 6,
    cosine_threshold: float = 0.45,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], bool]:
    """Assigns `speaker_id` (`SPK_1`, `SPK_2`, ...) to `segments` and saves project-scoped speaker clips.

    Per Decision 7c, extracted speaker reference clips live ONLY inside `speakers_dir`
    (`media/localize/proj_<id>/speakers/`) and are NEVER registered into the shared voice catalog.
    """
    if not segments:
        return [], {}, True

    spk_model = get_local_model(paths, "speaker_embedding_onnx")
    model_ready = bool(
        spk_model and spk_model.get("status") == "ready" and spk_model.get("installed_on_disk")
    )

    if not vocal_wav.is_file() or not model_ready:
        out_segs = [{**seg, "speaker_id": str(seg.get("speaker_id") or "SPK_1")} for seg in segments]
        prov, vid, lbl = _DEFAULT_VI_VOICES[0]
        return (
            out_segs,
            {"SPK_1": {"label": lbl, "provider": prov, "voice_id": vid, "ref_audio_rel": ""}},
            False,
        )

    try:
        import onnxruntime as ort
        import soundfile as sf
        import soxr
        from scipy.cluster.hierarchy import fcluster, linkage
        from scipy.spatial.distance import pdist
    except Exception as exc:
        logger.warning("Speaker diarization dependencies unavailable: %s", exc)
        out_segs = [{**seg, "speaker_id": "SPK_1"} for seg in segments]
        prov, vid, lbl = _DEFAULT_VI_VOICES[0]
        return (
            out_segs,
            {"SPK_1": {"label": lbl, "provider": prov, "voice_id": vid, "ref_audio_rel": ""}},
            False,
        )

    wav_raw, sr = sf.read(str(vocal_wav), dtype="float32", always_2d=True)
    mono = wav_raw.mean(axis=1).astype(np.float32)
    wav_16k = mono if sr == _FBANK_SR else soxr.resample(mono, sr, _FBANK_SR).astype(np.float32)
    total_16k = wav_16k.shape[0]

    onnx_path = Path(str(spk_model["local_path"]))
    if onnx_path.is_dir():
        onnx_path = next(onnx_path.glob("*.onnx"))

    sess_opts = ort.SessionOptions()
    sess_opts.intra_op_num_threads = 2
    sess_opts.inter_op_num_threads = 1
    sess = ort.InferenceSession(
        str(onnx_path),
        sess_options=sess_opts,
        providers=["CPUExecutionProvider"],
    )
    inp_name = sess.get_inputs()[0].name

    embeddings: list[np.ndarray | None] = []
    seg_rms_list: list[float] = []
    try:
        for seg in segments:
            st = max(0.0, float(seg.get("start_s") or 0.0))
            en = max(st + 0.35, float(seg.get("end_s") or (st + 1.0)))
            if en - st < 0.85:
                mid = 0.5 * (st + en)
                st = max(0.0, mid - 0.45)
                en = mid + 0.45
            i0 = min(total_16k, int(round(st * _FBANK_SR)))
            i1 = min(total_16k, max(i0 + int(0.35 * _FBANK_SR), int(round(en * _FBANK_SR))))
            clip = wav_16k[i0:i1]
            rms = float(np.sqrt(np.mean(clip * clip))) if clip.size > 0 else 0.0
            seg_rms_list.append(rms)
            if clip.size < int(0.25 * _FBANK_SR) or rms < 1e-4:
                embeddings.append(None)
                continue
            feat = _compute_kaldi_fbank_80(clip)[None].astype(np.float32)
            emb = sess.run(None, {inp_name: feat})[0][0].astype(np.float32)
            norm = float(np.linalg.norm(emb))
            embeddings.append(emb / norm if norm > 1e-8 else None)
    finally:
        del sess
        gc.collect()

    valid_indices = [idx for idx, e in enumerate(embeddings) if e is not None]
    raw_labels = [1] * len(segments)
    if len(valid_indices) >= 2:
        mat = np.stack([embeddings[idx] for idx in valid_indices if embeddings[idx] is not None], axis=0)
        dists = np.clip(pdist(mat, metric="cosine"), 0.0, 2.0)
        z = linkage(dists, method="average")
        clustered = fcluster(z, t=cosine_threshold, criterion="distance")
        if int(clustered.max()) > max_speakers:
            clustered = fcluster(z, t=max_speakers, criterion="maxclust")
        for pos, seg_idx in enumerate(valid_indices):
            raw_labels[seg_idx] = int(clustered[pos])
        # Propagate nearest neighbor speaker label to any ultra-short/silent segments
        for idx in range(len(segments)):
            if embeddings[idx] is None:
                nearest = min(valid_indices, key=lambda v: abs(v - idx))
                raw_labels[idx] = raw_labels[nearest]

    # Canonicalize speaker IDs in chronological order of appearance: SPK_1, SPK_2, ...
    remap: dict[int, str] = {}
    out_segs: list[dict[str, Any]] = []
    for idx, seg in enumerate(segments):
        r_lbl = raw_labels[idx]
        if r_lbl not in remap:
            remap[r_lbl] = f"SPK_{len(remap) + 1}"
        out_segs.append({**seg, "speaker_id": remap[r_lbl]})

    # Extract cleanest 4-8s project-scoped reference audio clip per speaker for optional cloning
    speakers_dir.mkdir(parents=True, exist_ok=True)
    wav_24k = mono if sr == _REF_SR else soxr.resample(mono, sr, _REF_SR).astype(np.float32)
    total_24k = wav_24k.shape[0]
    speaker_cfg: dict[str, dict[str, Any]] = {}

    for spk_idx, spk_id in enumerate(remap.values()):
        cand_idxs = [i for i, s in enumerate(out_segs) if s["speaker_id"] == spk_id]
        cand_idxs.sort(key=lambda i: seg_rms_list[i], reverse=True)
        chunks_24k: list[np.ndarray] = []
        acc_samples = 0
        target_samples = int(7.5 * _REF_SR)
        for ci in cand_idxs:
            st = max(0.0, float(out_segs[ci]["start_s"]))
            en = max(st + 0.3, float(out_segs[ci]["end_s"]))
            s0 = min(total_24k, int(round(st * _REF_SR)))
            s1 = min(total_24k, int(round(en * _REF_SR)))
            piece = wav_24k[s0:s1]
            if piece.size > int(0.25 * _REF_SR):
                chunks_24k.append(piece)
                acc_samples += int(piece.size)
                if acc_samples >= target_samples:
                    break

        ref_rel = ""
        if chunks_24k:
            joined = np.concatenate(chunks_24k)[: int(8.5 * _REF_SR)]
            # Pad gently by repeating if total speaker audio < 2.5s so encoder always has enough frames
            if joined.size < int(2.5 * _REF_SR) and joined.size > 0:
                reps = int(np.ceil((2.5 * _REF_SR) / joined.size))
                joined = np.tile(joined, reps)[: int(3.0 * _REF_SR)]
            ref_path = speakers_dir / f"{spk_id.lower()}_ref.wav"
            sf.write(str(ref_path), np.clip(joined, -1.0, 1.0), _REF_SR, subtype="PCM_16")
            try:
                ref_rel = str(ref_path.relative_to(media_root)).replace("\\", "/")
            except ValueError:
                ref_rel = str(ref_path)

        prov, vid, lbl = _DEFAULT_VI_VOICES[spk_idx % len(_DEFAULT_VI_VOICES)]
        speaker_cfg[spk_id] = {
            "label": f"Người nói {spk_idx + 1}" if len(remap) > 1 else lbl.split(" (")[0],
            "provider": prov,
            "voice_id": vid,
            "ref_audio_rel": ref_rel,
        }

    return out_segs, speaker_cfg, True

"""TTS synthesis (`edge-tts` Python API with WordBoundary, `VieNeu-TTS` v3 Nano CPU + zero-shot cloning, and `test_tone`), silence trim & timeline alignment."""
from __future__ import annotations

import asyncio
import gc
import logging
import math
import re
import shutil
import struct
import subprocess
import threading
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from videocreator.paths import AppPaths, get_paths
from videocreator.pipeline.ffmpeg import run_ffmpeg
from videocreator.pipeline.probe import probe_duration

logger = logging.getLogger("videocreator.tts.synthesizer")

_VTT_CUE_RE = re.compile(
    r"(?:(\d+):)?(\d{2}):(\d{2})[.,](\d{3})\s*-->\s*(?:(\d+):)?(\d{2}):(\d{2})[.,](\d{3})"
)


@dataclass(frozen=True)
class WordTiming:
    word: str
    start_s: float
    end_s: float


@dataclass(frozen=True)
class SynthesizedTrack:
    audio_path: Path
    duration_s: float
    word_timings: list[WordTiming]
    applied_atempo: float = 1.0
    provider: str = "edge"


class TTSUnavailableError(RuntimeError):
    """Raised when the configured TTS provider is offline or unavailable."""


def trim_voice_silence(src_audio: Path, dst_audio: Path) -> Path:
    """Decodes `src_audio` to 48kHz mono PCM WAV and strips only outer leading/trailing silence."""
    import numpy as np

    dst_audio.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(
        [
            "-i",
            str(src_audio.resolve()),
            "-c:a",
            "pcm_s16le",
            "-ar",
            "48000",
            "-ac",
            "1",
            str(dst_audio.resolve()),
        ]
    )
    try:
        with wave.open(str(dst_audio), "rb") as wf:
            sr = wf.getframerate()
            raw = wf.readframes(wf.getnframes())
        samples = np.frombuffer(raw, dtype=np.int16)
        # -45 dBFS threshold (~184 on int16); never touches internal pauses between words
        voiced = np.flatnonzero(np.abs(samples) > 184)
        if voiced.size > 0:
            start_idx = max(0, int(voiced[0]) - int(0.03 * sr))
            end_idx = min(int(samples.size), int(voiced[-1]) + int(0.06 * sr))
            if (end_idx - start_idx) >= int(0.12 * sr):
                trimmed = samples[start_idx:end_idx]
                with wave.open(str(dst_audio), "wb") as wf_out:
                    wf_out.setnchannels(1)
                    wf_out.setsampwidth(2)
                    wf_out.setframerate(sr)
                    wf_out.writeframes(trimmed.tobytes())
    except Exception:
        if not dst_audio.exists():
            shutil.copy2(src_audio, dst_audio)
    return dst_audio


def fit_voice_to_budget(
    audio_path: Path,
    target_duration_s: float,
    word_timings: list[WordTiming],
    *,
    max_atempo: float = 1.35,
    out_path: Path | None = None,
) -> tuple[Path, float, list[WordTiming], float]:
    """Fits synthesized audio cleanly inside `target_duration_s` using FFmpeg `atempo <= max_atempo`."""
    actual_dur = probe_duration(audio_path)
    if target_duration_s <= 0.2 or actual_dur <= target_duration_s + 0.05:
        return audio_path, actual_dur, list(word_timings), 1.0

    factor = min(max_atempo, max(1.0, actual_dur / max(0.3, target_duration_s)))
    if factor <= 1.02:
        return audio_path, actual_dur, list(word_timings), 1.0

    dest = out_path or audio_path.with_name(f"{audio_path.stem}_fitted.wav")
    run_ffmpeg(
        [
            "-i",
            str(audio_path.resolve()),
            "-af",
            f"atempo={factor:.3f}",
            "-c:a",
            "pcm_s16le",
            "-ar",
            "48000",
            "-ac",
            "1",
            str(dest.resolve()),
        ]
    )
    fitted_dur = probe_duration(dest)
    scaled_timings = [
        WordTiming(
            word=wt.word,
            start_s=round(wt.start_s / factor, 3),
            end_s=round(min(fitted_dur, wt.end_s / factor), 3),
        )
        for wt in word_timings
        if wt.end_s > wt.start_s
    ]
    return dest, fitted_dur, scaled_timings, round(factor, 3)


def _proportional_word_timings(text: str, duration_s: float) -> list[WordTiming]:
    words = [w for w in (text or "").strip().split() if w]
    if not words or duration_s <= 0.05:
        return []
    weights = [max(1, len(w)) for w in words]
    total_w = float(sum(weights))
    cursor = 0.0
    out: list[WordTiming] = []
    for w, wt in zip(words, weights):
        span = duration_s * (wt / total_w)
        st = round(cursor, 3)
        en = round(min(duration_s, cursor + max(0.04, span)), 3)
        if en > st:
            out.append(WordTiming(word=w, start_s=st, end_s=en))
        cursor += span
    return out


def _write_syllable_pcm_samples(
    wf: wave.Wave_write,
    duration_s: float,
    *,
    sample_rate: int = 48000,
    voiced: bool,
    base_freq: float = 210.0,
) -> None:
    n_samples = max(1, int(round(duration_s * sample_rate)))
    if not voiced:
        wf.writeframes(b"\x00\x00" * n_samples)
        return
    attack = min(n_samples // 6, int(0.015 * sample_rate))
    release = min(n_samples // 6, int(0.02 * sample_rate))
    buf = bytearray(n_samples * 2)
    two_pi = 2.0 * math.pi
    for i in range(n_samples):
        env = 1.0
        if attack > 0 and i < attack:
            env = i / attack
        elif release > 0 and i > (n_samples - release):
            env = max(0.0, (n_samples - i) / release)
        t = i / sample_rate
        signal = 0.65 * math.sin(two_pi * base_freq * t) + 0.35 * math.sin(
            two_pi * (base_freq * 1.5) * t
        )
        sample_val = int(max(-32767, min(32767, signal * env * 14000.0)))
        struct.pack_into("<h", buf, i * 2, sample_val)
    wf.writeframes(bytes(buf))


def _synthesize_local_waveform(
    lines: list[tuple[str, float]],
    *,
    work_dir: Path,
    trim_silence: bool = True,
) -> SynthesizedTrack:
    """Internal test-only tone cadence synthesizer (`test_tone`)."""
    work_dir.mkdir(parents=True, exist_ok=True)
    raw_wav = work_dir / "voice_raw.wav"
    lead_silence_s = 0.12
    trail_silence_s = 0.12
    word_dur_s = 0.24
    word_gap_s = 0.04
    line_gap_s = 0.08
    sample_rate = 48000

    timings: list[WordTiming] = []
    cursor_s = 0.0
    freq_idx = 0

    with wave.open(str(raw_wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)

        _write_syllable_pcm_samples(wf, lead_silence_s, sample_rate=sample_rate, voiced=False)
        for text, _shot_dur in lines:
            words = [w for w in (text or "").strip().split() if w]
            for w_idx, word in enumerate(words):
                freq = 195.0 + (freq_idx % 5) * 18.0
                freq_idx += 1
                start_t = round(cursor_s, 3)
                _write_syllable_pcm_samples(
                    wf, word_dur_s, sample_rate=sample_rate, voiced=True, base_freq=freq
                )
                end_t = round(cursor_s + word_dur_s, 3)
                timings.append(WordTiming(word=word, start_s=start_t, end_s=end_t))
                cursor_s += word_dur_s
                if w_idx < len(words) - 1:
                    _write_syllable_pcm_samples(
                        wf, word_gap_s, sample_rate=sample_rate, voiced=False
                    )
                    cursor_s += word_gap_s
            if words:
                _write_syllable_pcm_samples(
                    wf, line_gap_s, sample_rate=sample_rate, voiced=False
                )
                cursor_s += line_gap_s
        _write_syllable_pcm_samples(wf, trail_silence_s, sample_rate=sample_rate, voiced=False)

    final_wav = work_dir / "voice_trimmed.wav"
    if trim_silence:
        trim_voice_silence(raw_wav, final_wav)
    else:
        shutil.copy2(raw_wav, final_wav)

    dur = probe_duration(final_wav)
    clamped = [
        WordTiming(
            word=wt.word,
            start_s=round(min(wt.start_s, max(0.0, dur - 0.05)), 3),
            end_s=round(min(wt.end_s, dur), 3),
        )
        for wt in timings
        if wt.end_s > wt.start_s
    ]
    return SynthesizedTrack(
        audio_path=final_wav,
        duration_s=dur,
        word_timings=clamped,
        applied_atempo=1.0,
        provider="test_tone",
    )


def _parse_vtt_timings(vtt_text: str) -> list[WordTiming]:
    timings: list[WordTiming] = []
    blocks = re.split(r"\r?\n\s*\r?\n", vtt_text.strip())
    for block in blocks:
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        for i, ln in enumerate(lines):
            m = _VTT_CUE_RE.search(ln)
            if not m:
                continue
            h1, m1, s1, ms1, h2, m2, s2, ms2 = m.groups()
            start_s = int(h1 or 0) * 3600 + int(m1) * 60 + int(s1) + int(ms1) / 1000.0
            end_s = int(h2 or 0) * 3600 + int(m2) * 60 + int(s2) + int(ms2) / 1000.0
            cue_text = re.sub(r"<[^>]+>", "", " ".join(lines[i + 1 :])).strip()
            words = cue_text.split()
            if not words or end_s <= start_s:
                break
            span = (end_s - start_s) / len(words)
            for idx, w in enumerate(words):
                timings.append(
                    WordTiming(
                        word=w,
                        start_s=round(start_s + idx * span, 3),
                        end_s=round(start_s + (idx + 1) * span, 3),
                    )
                )
            break
    return timings


def _run_coro_sync(coro: Any) -> Any:
    """Executes an async coroutine safely whether or not the current thread already runs an event loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    box: dict[str, Any] = {}

    def _runner() -> None:
        try:
            box["res"] = asyncio.run(coro)
        except BaseException as exc:  # noqa: BLE001
            box["err"] = exc

    t = threading.Thread(target=_runner, daemon=True)
    t.start()
    t.join(timeout=90.0)
    if "err" in box:
        raise box["err"]
    return box.get("res")


def _synthesize_edge_python_or_cli(
    script_text: str,
    *,
    voice: str,
    work_dir: Path,
    stem: str = "edge_raw",
) -> SynthesizedTrack:
    """Synthesizes speech via Python `edge_tts` library (with exact `WordBoundary` timings), or CLI fallback."""
    if not script_text.strip():
        raise TTSUnavailableError("Lời thoại trống, không thể đọc TTS")

    work_dir.mkdir(parents=True, exist_ok=True)
    clean_voice = voice.replace("-Female", "").replace("-Male", "").strip() or "vi-VN-HoaiMyNeural"
    tts_input = script_text.strip()
    if tts_input and tts_input[-1] not in ".!?…":
        tts_input = f"{tts_input}."
    raw_mp3 = work_dir / f"{stem}.mp3"
    trimmed_wav = work_dir / f"{stem}_trimmed.wav"

    try:
        import edge_tts

        async def _stream_with_retries() -> list[WordTiming]:
            last_exc: Exception | None = None
            for attempt in range(4):
                try:
                    comm = edge_tts.Communicate(tts_input, clean_voice, boundary="WordBoundary")
                    audio_chunks = bytearray()
                    w_timings: list[WordTiming] = []
                    async for chunk in comm.stream():
                        ctype = chunk.get("type")
                        if ctype == "audio":
                            audio_chunks.extend(chunk.get("data") or b"")
                        elif ctype in ("WordBoundary", "SentenceBoundary"):
                            txt = str(chunk.get("text") or "").strip()
                            off_s = float(chunk.get("offset") or 0.0) / 10_000_000.0
                            dur_s = max(0.05, float(chunk.get("duration") or 500_000.0) / 10_000_000.0)
                            if txt:
                                if ctype == "WordBoundary":
                                    w_timings.append(
                                        WordTiming(word=txt, start_s=round(off_s, 3), end_s=round(off_s + dur_s, 3))
                                    )
                                elif not w_timings:
                                    words = txt.split()
                                    span = dur_s / max(1, len(words))
                                    for wi, wd in enumerate(words):
                                        w_timings.append(
                                            WordTiming(
                                                word=wd,
                                                start_s=round(off_s + wi * span, 3),
                                                end_s=round(off_s + (wi + 1) * span, 3),
                                            )
                                        )
                    if len(audio_chunks) >= 256:
                        raw_mp3.write_bytes(bytes(audio_chunks))
                        return w_timings
                    last_exc = TTSUnavailableError("Edge TTS returned empty audio stream")
                except Exception as exc:
                    last_exc = exc
                if attempt < 3:
                    await asyncio.sleep(0.8 * (attempt + 1))
            assert last_exc is not None
            raise last_exc

        timings = _run_coro_sync(_stream_with_retries())
        trim_voice_silence(raw_mp3, trimmed_wav)
        dur = probe_duration(trimmed_wav)
        if not timings:
            timings = _proportional_word_timings(script_text, dur)
        else:
            timings = [
                WordTiming(
                    word=wt.word,
                    start_s=round(min(wt.start_s, max(0.0, dur - 0.04)), 3),
                    end_s=round(min(wt.end_s, dur), 3),
                )
                for wt in timings
                if wt.end_s > wt.start_s
            ]
        return SynthesizedTrack(
            audio_path=trimmed_wav,
            duration_s=dur,
            word_timings=timings,
            applied_atempo=1.0,
            provider="edge",
        )
    except ImportError:
        pass
    except Exception as exc:
        logger.debug("edge_tts Python API failed (%s); trying CLI fallback", exc)

    exe = shutil.which("edge-tts")
    if not exe:
        raise TTSUnavailableError("Edge TTS không kết nối được máy chủ hoặc chưa cài đặt")

    raw_vtt = work_dir / f"{stem}.vtt"
    try:
        proc = subprocess.run(
            [
                exe,
                "--voice",
                clean_voice,
                "--text",
                script_text,
                "--write-media",
                str(raw_mp3),
                "--write-subtitles",
                str(raw_vtt),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )
    except Exception as exc:
        raise TTSUnavailableError(f"Edge TTS lỗi thực thi: {exc}") from exc

    if proc.returncode != 0 or not raw_mp3.exists() or raw_mp3.stat().st_size < 256:
        raise TTSUnavailableError(
            f"Edge TTS thất bại: {(proc.stderr or proc.stdout or 'no output')[-300:]}"
        )

    trim_voice_silence(raw_mp3, trimmed_wav)
    dur = probe_duration(trimmed_wav)
    timings = (
        _parse_vtt_timings(raw_vtt.read_text(encoding="utf-8", errors="replace"))
        if raw_vtt.exists()
        else _proportional_word_timings(script_text, dur)
    )
    return SynthesizedTrack(
        audio_path=trimmed_wav,
        duration_s=dur,
        word_timings=timings,
        applied_atempo=1.0,
        provider="edge",
    )


def _resolve_vieneu_model_dir(paths: AppPaths | None = None) -> Path:
    from videocreator.models_manager import get_local_model

    app_paths = paths or get_paths()
    info = get_local_model(app_paths, "vieneu_tts_vi")
    if not (info and info.get("status") == "ready" and info.get("installed_on_disk")):
        raise TTSUnavailableError(
            "Model 'vieneu_tts_vi' chưa cài đặt hoặc chưa vượt qua kiểm thử CPU trong Cài đặt."
        )
    model_dir = Path(str(info["local_path"]))
    return model_dir if model_dir.is_dir() else model_dir.parent


def synthesize_vieneu_single(
    text: str,
    *,
    work_dir: Path,
    voice: str = "Minh Quân",
    ref_audio: Path | None = None,
    paths: AppPaths | None = None,
    stem: str = "vieneu_raw",
    tts_instance: Any = None,
    enrolled_voice: dict[str, Any] | None = None,
) -> SynthesizedTrack:
    """Synthesizes Vietnamese speech on CPU via `V3NanoVieNeuTTS` (preset voice or cloned `ref_audio`)."""
    import numpy as np
    import soundfile as sf

    clean_txt = (text or "").strip()
    if not clean_txt:
        raise TTSUnavailableError("Lời thoại trống, không thể đọc VieNeu-TTS")

    work_dir.mkdir(parents=True, exist_ok=True)
    own_instance = tts_instance is None
    if own_instance:
        from vieneu.v3nano import V3NanoVieNeuTTS

        model_dir = _resolve_vieneu_model_dir(paths)
        tts = V3NanoVieNeuTTS(onnx_dir=str(model_dir))
    else:
        tts = tts_instance

    try:
        if enrolled_voice is not None:
            wav_24k = tts.infer(clean_txt, voice=enrolled_voice, apply_watermark=False)
        elif ref_audio is not None and ref_audio.is_file():
            wav_24k = tts.infer(clean_txt, ref_audio=str(ref_audio), apply_watermark=False)
        else:
            preset_name = (voice or "").replace("vieneu:", "").strip() or None
            if preset_name and preset_name not in tts._preset_voices:
                preset_name = None
            wav_24k = tts.infer(clean_txt, voice=preset_name, apply_watermark=False)

        if wav_24k is None or len(wav_24k) < 400:
            raise TTSUnavailableError("VieNeu-TTS sinh âm thanh rỗng")

        raw_24k_wav = work_dir / f"{stem}_24k.wav"
        sf.write(str(raw_24k_wav), np.clip(wav_24k, -1.0, 1.0), int(tts.sample_rate), subtype="PCM_16")
        trimmed_wav = trim_voice_silence(raw_24k_wav, work_dir / f"{stem}_trimmed.wav")
        raw_24k_wav.unlink(missing_ok=True)
        dur = probe_duration(trimmed_wav)
        return SynthesizedTrack(
            audio_path=trimmed_wav,
            duration_s=dur,
            word_timings=_proportional_word_timings(clean_txt, dur),
            applied_atempo=1.0,
            provider="vieneu",
        )
    except TTSUnavailableError:
        raise
    except Exception as exc:
        raise TTSUnavailableError(f"VieNeu-TTS lỗi tổng hợp giọng: {exc}") from exc
    finally:
        if own_instance:
            tts.close()
            gc.collect()


def synthesize_speech_segments(
    lines: list[tuple[str, float]],
    *,
    lang: str,
    voice: str,
    provider_name: str,
    work_dir: Path,
    max_atempo: float = 1.35,
    ref_audio: Path | None = None,
    paths: AppPaths | None = None,
) -> tuple[SynthesizedTrack, list[str]]:
    """Synthesizes continuous voice-over from `(text, shot_duration_s)` tuples and fits duration."""
    non_empty = [(t.strip(), float(d)) for t, d in lines if t and t.strip()]
    if not non_empty:
        raise TTSUnavailableError("Không có lời thoại để lồng tiếng")

    target_dur = sum(max(0.5, float(d)) for _, d in lines)
    prov = (provider_name or "edge").strip().lower()
    is_tone_sim = prov in ("test_tone", "local")
    script_text = ". ".join(t for t, _ in non_empty)

    if is_tone_sim:
        raw_track = _synthesize_local_waveform(lines, work_dir=work_dir)
    elif prov == "edge":
        try:
            raw_track = _synthesize_edge_python_or_cli(script_text, voice=voice, work_dir=work_dir)
        except TTSUnavailableError:
            if lang == "vi":
                vn_preset = "NamMinh" in voice and "Minh Quân" or "Trúc Ly"
                raw_track = synthesize_vieneu_single(
                    script_text, work_dir=work_dir, voice=vn_preset, paths=paths
                )
                prov = "vieneu"
            else:
                raise
    elif prov == "vieneu":
        raw_track = synthesize_vieneu_single(
            script_text,
            work_dir=work_dir,
            voice=voice,
            ref_audio=ref_audio,
            paths=paths,
        )
    else:
        raise TTSUnavailableError(f"Chưa hỗ trợ TTS provider '{provider_name}'")

    fitted_path, fitted_dur, fitted_timings, factor = fit_voice_to_budget(
        raw_track.audio_path,
        target_dur,
        raw_track.word_timings,
        max_atempo=max_atempo,
        out_path=work_dir / "voice_fitted.wav",
    )
    warnings: list[str] = []
    if is_tone_sim:
        warnings.append("Đang dùng âm hiệu nhịp kiểm thử (test_tone), không phải giọng người thật.")
    if factor > 1.02:
        warnings.append(
            f"Tự động tăng nhịp giọng x{factor:.2f} để khớp tổng thời lượng hình {target_dur:.1f}s"
        )
    if fitted_dur > target_dur + 0.35:
        warnings.append(
            f"Lời đọc dài {fitted_dur:.1f}s vượt hình {target_dur:.1f}s: phần cuối có thể bị cắt, nên rút gọn chữ ({lang})"
        )

    return (
        SynthesizedTrack(
            audio_path=fitted_path,
            duration_s=fitted_dur,
            word_timings=fitted_timings,
            applied_atempo=factor,
            provider=prov,
        ),
        warnings,
    )


def synthesize_timed_speaker_segments(
    paths: AppPaths,
    timed_items: list[dict[str, Any]],
    *,
    work_dir: Path,
    preview_out_dir: Path | None = None,
    max_atempo: float = 1.35,
) -> tuple[SynthesizedTrack, list[str], list[str]]:
    """Synthesizes per-segment multi-speaker audio aligned to exact timeline offsets `[offset_s, offset_s + dur_s]`.

    Each item in `timed_items` expects:
      `{"text": str, "offset_s": float, "duration_s": float, "provider": str, "voice": str, "ref_audio": Path | None}`
    Returns `(master_track, preview_paths, warnings)`.
    """
    import numpy as np
    import soundfile as sf

    work_dir.mkdir(parents=True, exist_ok=True)
    if preview_out_dir is not None:
        preview_out_dir.mkdir(parents=True, exist_ok=True)

    sr = 48000
    total_dur = max(
        0.8,
        max((float(it["offset_s"]) + float(it["duration_s"]) for it in timed_items), default=1.0),
    )
    master_samples = np.zeros(int(round(total_dur * sr)) + sr // 4, dtype=np.float32)
    all_timings: list[WordTiming] = []
    preview_files: list[str] = []
    warnings: list[str] = []
    used_providers: set[str] = set()

    # Reuse a single V3NanoVieNeuTTS session & enrolled reference cache across segments to keep RAM/CPU low
    needs_vieneu = any(str(it.get("provider") or "").lower() == "vieneu" for it in timed_items)
    vieneu_tts = None
    enrolled_cache: dict[str, dict[str, Any]] = {}
    if needs_vieneu:
        from vieneu.v3nano import V3NanoVieNeuTTS

        model_dir = _resolve_vieneu_model_dir(paths)
        vieneu_tts = V3NanoVieNeuTTS(onnx_dir=str(model_dir))

    try:
        for idx, item in enumerate(timed_items):
            txt = str(item.get("text") or "").strip()
            off_s = max(0.0, float(item.get("offset_s") or 0.0))
            dur_s = max(0.45, float(item.get("duration_s") or 1.5))
            prov = str(item.get("provider") or "edge").strip().lower()
            voice = str(item.get("voice") or "vi-VN-HoaiMyNeural").strip()
            ref_audio: Path | None = item.get("ref_audio")
            stem = f"seg_{idx:03d}"

            if not txt:
                preview_files.append("")
                continue

            if prov in ("test_tone", "local"):
                seg_track = _synthesize_local_waveform([(txt, dur_s)], work_dir=work_dir / stem)
                used_providers.add("test_tone")
            elif prov == "vieneu":
                enrolled = None
                if ref_audio is not None and ref_audio.is_file() and vieneu_tts is not None:
                    cache_key = str(ref_audio.resolve())
                    if cache_key not in enrolled_cache:
                        spk_emb, style_tok = vieneu_tts.encode_reference(str(ref_audio), denoise=True)
                        enrolled_cache[cache_key] = {"speaker_emb": spk_emb, "style": style_tok}
                    enrolled = enrolled_cache[cache_key]
                seg_track = synthesize_vieneu_single(
                    txt,
                    work_dir=work_dir / stem,
                    voice=voice,
                    ref_audio=ref_audio if enrolled is None else None,
                    paths=paths,
                    stem=stem,
                    tts_instance=vieneu_tts,
                    enrolled_voice=enrolled,
                )
                used_providers.add("vieneu")
            else:
                try:
                    seg_track = _synthesize_edge_python_or_cli(
                        txt,
                        voice=voice,
                        work_dir=work_dir / stem,
                        stem=stem,
                    )
                    used_providers.add("edge")
                except TTSUnavailableError:
                    if voice.lower().startswith("vi-"):
                        if vieneu_tts is None:
                            from vieneu.v3nano import V3NanoVieNeuTTS

                            vieneu_tts = V3NanoVieNeuTTS(onnx_dir=str(_resolve_vieneu_model_dir(paths)))
                        vn_voice = "Minh Quân" if "nam" in voice.lower() else "Trúc Ly"
                        seg_track = synthesize_vieneu_single(
                            txt,
                            work_dir=work_dir / stem,
                            voice=vn_voice,
                            paths=paths,
                            stem=stem,
                            tts_instance=vieneu_tts,
                        )
                        used_providers.add("vieneu")
                    else:
                        raise

            fitted_wav, _f_dur, f_timings, factor = fit_voice_to_budget(
                seg_track.audio_path,
                dur_s,
                seg_track.word_timings,
                max_atempo=max_atempo,
                out_path=work_dir / stem / f"{stem}_fitted.wav",
            )
            if factor > 1.28:
                warnings.append(f"Đoạn #{idx + 1}: tăng tốc giọng x{factor:.2f}")

            if preview_out_dir is not None:
                prev_dst = preview_out_dir / f"seg_{idx:03d}.wav"
                shutil.copy2(fitted_wav, prev_dst)
                preview_files.append(str(prev_dst))
            else:
                preview_files.append(str(fitted_wav))

            seg_pcm, seg_sr = sf.read(str(fitted_wav), dtype="float32", always_2d=False)
            if seg_pcm.ndim > 1:
                seg_pcm = seg_pcm.mean(axis=1)
            if seg_sr != sr:
                import soxr

                seg_pcm = soxr.resample(seg_pcm, seg_sr, sr).astype(np.float32)

            # Cap to segment window + tiny 60ms tail so adjacent segments never collide loudly
            max_len = int(round((dur_s + 0.06) * sr))
            seg_pcm = seg_pcm[:max_len]
            start_sample = int(round(off_s * sr))
            end_sample = start_sample + seg_pcm.shape[0]
            if end_sample > master_samples.shape[0]:
                master_samples = np.pad(master_samples, (0, end_sample - master_samples.shape[0]))
            master_samples[start_sample:end_sample] += seg_pcm

            for wt in f_timings:
                w_st = round(off_s + wt.start_s, 3)
                w_en = round(min(off_s + dur_s, off_s + wt.end_s), 3)
                if w_en > w_st:
                    all_timings.append(WordTiming(word=wt.word, start_s=w_st, end_s=w_en))
    finally:
        if vieneu_tts is not None:
            vieneu_tts.close()
            del vieneu_tts
            gc.collect()

    master_wav = work_dir / "voice_master.wav"
    trimmed_samples = np.clip(master_samples[: int(round(total_dur * sr))], -1.0, 1.0)
    sf.write(str(master_wav), trimmed_samples, sr, subtype="PCM_16")
    actual_dur = probe_duration(master_wav)
    prov_summary = "+".join(sorted(used_providers)) if used_providers else "edge"
    return (
        SynthesizedTrack(
            audio_path=master_wav,
            duration_s=actual_dur,
            word_timings=all_timings,
            applied_atempo=1.0,
            provider=prov_summary,
        ),
        preview_files,
        warnings,
    )

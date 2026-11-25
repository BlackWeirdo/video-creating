"""NumPy PCM outer-silence trimming (`-45 dBFS`), FFmpeg `atempo` fitting, and proportional word timings."""
from __future__ import annotations

import shutil
import wave
from pathlib import Path

from videocreator.pipeline.ffmpeg import run_ffmpeg
from videocreator.pipeline.probe import probe_duration
from videocreator.tts.types import WordTiming


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


def proportional_word_timings(text: str, duration_s: float) -> list[WordTiming]:
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

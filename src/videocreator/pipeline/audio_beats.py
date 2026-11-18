"""Lightweight pure-Python + FFmpeg music BPM, beat grid, mood/energy analyser, and cut beat-snapper.

Follows the beat-grid methodology in `vendor/skills/video-shotcraft/references/music-beat-sync.md`
without requiring heavy external DSP packages (`librosa`/`scipy`).
"""
from __future__ import annotations

import array
import math
import subprocess
from pathlib import Path
from typing import Any, Literal

from videocreator.paths import find_ffmpeg_binary

SAMPLE_RATE = 4000
HOP_SAMPLES = 40  # 10 ms per envelope frame (100 Hz envelope rate)
ENV_HZ = SAMPLE_RATE // HOP_SAMPLES

CALM_KEYWORDS = ("calm", "piano", "ambient", "lofi", "ballad", "chill", "êm", "nhẹ", "ấm", "sang", "buồn", "acoustic")
ENERGETIC_KEYWORDS = ("upbeat", "fast", "dance", "trap", "house", "phonk", "pop", "beat", "nhanh", "sôi động", "mạnh", "dồn dập")


def _decode_mono_pcm(audio_path: Path, max_seconds: float = 90.0) -> array.array[int]:
    """Decodes up to `max_seconds` of `audio_path` as 4000 Hz mono signed 16-bit PCM using FFmpeg."""
    ffmpeg_bin = find_ffmpeg_binary("ffmpeg")
    proc = subprocess.run(
        [
            ffmpeg_bin,
            "-v",
            "error",
            "-t",
            f"{max_seconds:.2f}",
            "-i",
            str(audio_path),
            "-af",
            "highpass=f=35,lowpass=f=1600",
            "-ac",
            "1",
            "-ar",
            str(SAMPLE_RATE),
            "-f",
            "s16le",
            "-",
        ],
        capture_output=True,
        timeout=25,
        check=False,
    )
    if proc.returncode != 0 or len(proc.stdout) < SAMPLE_RATE * 2:
        return array.array("h")
    usable_len = len(proc.stdout) - (len(proc.stdout) % 2)
    samples = array.array("h")
    samples.frombytes(proc.stdout[:usable_len])
    return samples


def _infer_mood_tags(title_hint: str, energy_level: str, bpm: float) -> list[str]:
    lower = title_hint.lower()
    tags: list[str] = []
    if energy_level == "energetic" or any(k in lower for k in ENERGETIC_KEYWORDS):
        tags.extend(["sôi động", "hiện đại", "nhịp nhanh", "energetic"])
    elif energy_level == "calm" or any(k in lower for k in CALM_KEYWORDS):
        tags.extend(["ấm áp", "nhẹ nhàng", "sang trọng", "tinh tế", "calm"])
    else:
        tags.extend(["sang trọng", "hiện đại", "vừa phải", "ấm áp", "moderate"])
    if bpm >= 120:
        tags.append("bắt beat")
    return list(dict.fromkeys(tags))


def analyse_music_beats(
    audio_path: Path,
    *,
    title_hint: str = "",
    max_seconds: float = 90.0,
) -> dict[str, Any]:
    """Extracts `bpm`, `energy_level`, `mood_tags`, `beat_times_s`, and `strong_beats_s` from an audio file."""
    samples = _decode_mono_pcm(audio_path, max_seconds=max_seconds)
    n_frames = len(samples) // HOP_SAMPLES
    if n_frames < ENV_HZ:
        return {
            "bpm": 100.0,
            "energy_level": "moderate",
            "mood_tags": _infer_mood_tags(title_hint or audio_path.stem, "moderate", 100.0),
            "beat_times_s": [],
            "strong_beats_s": [],
        }

    rms_env: list[float] = [0.0] * n_frames
    for f_idx in range(n_frames):
        base = f_idx * HOP_SAMPLES
        chunk = samples[base : base + HOP_SAMPLES]
        acc = 0.0
        for val in chunk:
            norm = val / 32768.0
            acc += norm * norm
        rms_env[f_idx] = math.sqrt(acc / HOP_SAMPLES)

    onset_env: list[float] = [0.0] * n_frames
    for f_idx in range(1, n_frames):
        diff = rms_env[f_idx] - rms_env[f_idx - 1]
        if diff > 0.0:
            onset_env[f_idx] = diff

    mean_rms = sum(rms_env) / max(1, n_frames)
    mean_onset = sum(onset_env) / max(1, n_frames)
    if mean_rms <= 1e-4 or mean_onset <= 1e-5:
        return {
            "bpm": 0.0,
            "energy_level": "calm",
            "mood_tags": _infer_mood_tags(title_hint or audio_path.stem, "calm", 0.0),
            "beat_times_s": [],
            "strong_beats_s": [],
        }

    # Autocorrelation over 68..176 BPM -> lag 34..88 frames at 100 Hz
    min_lag = 34  # ~176.5 BPM
    max_lag = min(88, n_frames // 2)  # ~68.2 BPM
    if max_lag <= min_lag:
        max_lag = max(min_lag + 1, n_frames - 1)

    raw_ac: dict[int, float] = {}
    for lag in range(min_lag, min(n_frames, max_lag * 2 + 1)):
        total = 0.0
        limit = n_frames - lag
        for i in range(limit):
            oi = onset_env[i]
            if oi > 0.0:
                total += oi * onset_env[i + lag]
        raw_ac[lag] = total / max(1, limit)

    best_lag = 50  # default 120 BPM
    best_score = -1.0
    for lag in range(min_lag, max_lag + 1):
        bpm_cand = 60.0 * ENV_HZ / lag
        # Gentle perceptual tempo prior centered around 115 BPM + 2x harmonic reinforcement
        tempo_prior = math.exp(-0.5 * ((bpm_cand - 115.0) / 45.0) ** 2)
        harmonic = raw_ac.get(lag * 2, 0.0) * 0.35
        score = (raw_ac.get(lag, 0.0) + harmonic) * (0.75 + 0.25 * tempo_prior)
        if score > best_score:
            best_score = score
            best_lag = lag

    bpm = round(60.0 * ENV_HZ / best_lag, 2)

    # Phase search (0 .. best_lag - 1) maximizing onset hits on integer beats
    best_phase = 0
    best_phase_energy = -1.0
    for phase in range(best_lag):
        p_sum = 0.0
        idx = phase
        while idx < n_frames:
            lo = max(0, idx - 1)
            hi = min(n_frames, idx + 2)
            p_sum += max(onset_env[lo:hi])
            idx += best_lag
        if p_sum > best_phase_energy:
            best_phase_energy = p_sum
            best_phase = phase

    beat_hits: list[tuple[float, float]] = []
    idx = best_phase
    while idx < n_frames:
        # Snap within +/- 3 frames (30ms) to strongest local transient peak
        lo = max(0, idx - 3)
        hi = min(n_frames, idx + 4)
        peak_idx = max(range(lo, hi), key=lambda k: onset_env[k])
        hit_strength = onset_env[peak_idx]
        t_sec = round((peak_idx if hit_strength > mean_onset * 1.5 else idx) / ENV_HZ, 3)
        if not beat_hits or t_sec - beat_hits[-1][0] >= 0.22:
            beat_hits.append((t_sec, hit_strength))
        idx += best_lag

    beat_times_s = [t for t, _ in beat_hits]
    ranked_hits = sorted(beat_hits, key=lambda pair: pair[1], reverse=True)
    strong_count = max(1, min(12, len(beat_hits) // 4))
    strong_beats_s = sorted(t for t, _ in ranked_hits[:strong_count])

    transient_ratio = mean_onset / max(1e-5, mean_rms)
    energy_level: Literal["calm", "moderate", "energetic"]
    lower_title = (title_hint or audio_path.stem).lower()
    if any(k in lower_title for k in ENERGETIC_KEYWORDS) or (bpm >= 118.0 and transient_ratio >= 0.16):
        energy_level = "energetic"
    elif any(k in lower_title for k in CALM_KEYWORDS) or (bpm < 92.0 and transient_ratio < 0.12):
        energy_level = "calm"
    else:
        energy_level = "moderate"

    return {
        "bpm": bpm,
        "energy_level": energy_level,
        "mood_tags": _infer_mood_tags(title_hint or audio_path.stem, energy_level, bpm),
        "beat_times_s": beat_times_s[:200],
        "strong_beats_s": strong_beats_s,
    }


def snap_shots_to_beats(
    planned_shots: list[dict[str, Any]],
    shot_bounds: dict[int, tuple[float, float]],
    beat_times_s: list[float],
    *,
    max_shift_s: float = 0.35,
    min_shot_s: float = 0.7,
) -> list[dict[str, Any]]:
    """Adjusts each shot's `duration_s` within `±max_shift_s` (and strictly inside its source `[start_s, end_s]`)
    so cumulative cut transitions land cleanly on music beats."""
    if not planned_shots or len(beat_times_s) < 2:
        return [dict(s) for s in planned_shots]

    sorted_beats = sorted(float(b) for b in beat_times_s if float(b) >= 0.0)
    snapped: list[dict[str, Any]] = []
    cursor_s = 0.0

    for idx, raw in enumerate(planned_shots):
        item = dict(raw)
        shot_id = int(item.get("shot_id") or 0)
        start_s = float(item.get("start_s") or 0.0)
        dur_s = float(item.get("duration_s") or 1.5)
        bounds = shot_bounds.get(shot_id)
        max_avail_dur = (float(bounds[1]) - start_s) if bounds is not None else dur_s
        max_avail_dur = max(dur_s, round(max_avail_dur, 3))

        # Snap every cut transition (and final ending if close to a beat)
        target_end_s = cursor_s + dur_s
        best_dur = dur_s
        best_dist = max_shift_s + 1e-6

        for bt in sorted_beats:
            if bt < target_end_s - max_shift_s:
                continue
            if bt > target_end_s + max_shift_s:
                break
            cand_dur = round(bt - cursor_s, 3)
            if cand_dur < min_shot_s or cand_dur > max_avail_dur + 1e-6:
                continue
            dist = abs(bt - target_end_s)
            if dist < best_dist:
                best_dist = dist
                best_dur = min(cand_dur, max_avail_dur)

        # Keep last shot untouched if snapping would make total shorter than 2.0s
        if idx == len(planned_shots) - 1 and cursor_s + best_dur < 2.0:
            best_dur = dur_s

        item["duration_s"] = round(best_dur, 3)
        snapped.append(item)
        cursor_s += item["duration_s"]

    return snapped

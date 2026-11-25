"""Deterministic local test-tone PCM waveform generator (`test_tone`)."""
from __future__ import annotations

import math
import shutil
import struct
import wave
from pathlib import Path

from videocreator.pipeline.probe import probe_duration
from videocreator.tts.audio_fit import trim_voice_silence
from videocreator.tts.types import SynthesizedTrack, WordTiming


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


def synthesize_local_waveform(
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

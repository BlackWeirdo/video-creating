"""Internal FFmpeg-ready TTS synthesis (`local` waveform + `edge-tts`), silence trim & atempo fit."""
from __future__ import annotations

import math
import re
import shutil
import struct
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path

from videocreator.pipeline.ffmpeg import run_ffmpeg
from videocreator.pipeline.probe import probe_duration

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
    provider: str = "local"


class TTSUnavailableError(RuntimeError):
    """Raised when the configured TTS provider is offline or unavailable."""


def trim_voice_silence(src_audio: Path, dst_audio: Path) -> Path:
    """Strips leading/trailing near-silence using FFmpeg `silenceremove`."""
    dst_audio.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(
        [
            "-i",
            str(src_audio.resolve()),
            "-af",
            "silenceremove=start_periods=1:start_duration=0.04:start_threshold=-45dB:"
            "stop_periods=1:stop_duration=0.08:stop_threshold=-45dB",
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
        trimmed_dur = probe_duration(dst_audio)
    except Exception:
        trimmed_dur = 0.0
    if trimmed_dur < 0.12:
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
    """Offline acoustic speech-cadence synthesizer with exact `WordTiming` metadata."""
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
        provider="local",
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
            start_s = (
                int(h1 or 0) * 3600 + int(m1) * 60 + int(s1) + int(ms1) / 1000.0
            )
            end_s = (
                int(h2 or 0) * 3600 + int(m2) * 60 + int(s2) + int(ms2) / 1000.0
            )
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


def _synthesize_edge_cli(
    lines: list[tuple[str, float]],
    *,
    voice: str,
    work_dir: Path,
) -> SynthesizedTrack:
    exe = shutil.which("edge-tts")
    if not exe:
        raise TTSUnavailableError("Chưa cài `edge-tts` CLI trên máy")
    script_text = ". ".join(text.strip() for text, _ in lines if text and text.strip())
    if not script_text:
        raise TTSUnavailableError("Lời thoại trống, không thể đọc TTS")

    work_dir.mkdir(parents=True, exist_ok=True)
    clean_voice = voice.replace("-Female", "").replace("-Male", "").strip() or "vi-VN-HoaiMyNeural"
    raw_mp3 = work_dir / "edge_raw.mp3"
    raw_vtt = work_dir / "edge_raw.vtt"
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

    trimmed_wav = trim_voice_silence(raw_mp3, work_dir / "voice_trimmed.wav")
    timings = (
        _parse_vtt_timings(raw_vtt.read_text(encoding="utf-8", errors="replace"))
        if raw_vtt.exists()
        else []
    )
    return SynthesizedTrack(
        audio_path=trimmed_wav,
        duration_s=probe_duration(trimmed_wav),
        word_timings=timings,
        applied_atempo=1.0,
        provider="edge",
    )


def synthesize_speech_segments(
    lines: list[tuple[str, float]],
    *,
    lang: str,
    voice: str,
    provider_name: str,
    work_dir: Path,
    max_atempo: float = 1.35,
) -> tuple[SynthesizedTrack, list[str]]:
    """Synthesizes continuous voice-over from `(text, shot_duration_s)` tuples and fits duration."""
    non_empty = [(t.strip(), float(d)) for t, d in lines if t and t.strip()]
    if not non_empty:
        raise TTSUnavailableError("Không có lời thoại để lồng tiếng")

    target_dur = sum(max(0.5, float(d)) for _, d in lines)
    prov = (provider_name or "local").strip().lower()
    if prov == "local":
        raw_track = _synthesize_local_waveform(lines, work_dir=work_dir)
    elif prov == "edge":
        raw_track = _synthesize_edge_cli(lines, voice=voice, work_dir=work_dir)
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

"""Edge TTS WebSocket (`WordBoundary`) and CLI fallback synthesis engine."""
from __future__ import annotations

import asyncio
import logging
import re
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any

from videocreator.pipeline.probe import probe_duration
from videocreator.tts.audio_fit import proportional_word_timings, trim_voice_silence
from videocreator.tts.types import SynthesizedTrack, TTSUnavailableError, WordTiming

logger = logging.getLogger("videocreator.tts.edge_engine")

_VTT_CUE_RE = re.compile(
    r"(?:(\d+):)?(\d{2}):(\d{2})[.,](\d{3})\s*-->\s*(?:(\d+):)?(\d{2}):(\d{2})[.,](\d{3})"
)


def parse_vtt_timings(vtt_text: str) -> list[WordTiming]:
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


def run_coro_sync(coro: Any) -> Any:
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


def synthesize_edge_python_or_cli(
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
    clean_voice = (
        voice.replace("-Female", "").replace("-Male", "").strip() or "vi-VN-HoaiMyNeural"
    )
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
                            dur_s = max(
                                0.05, float(chunk.get("duration") or 500_000.0) / 10_000_000.0
                            )
                            if txt:
                                if ctype == "WordBoundary":
                                    w_timings.append(
                                        WordTiming(
                                            word=txt,
                                            start_s=round(off_s, 3),
                                            end_s=round(off_s + dur_s, 3),
                                        )
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

        timings = run_coro_sync(_stream_with_retries())
        trim_voice_silence(raw_mp3, trimmed_wav)
        dur = probe_duration(trimmed_wav)
        if not timings:
            timings = proportional_word_timings(script_text, dur)
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
        parse_vtt_timings(raw_vtt.read_text(encoding="utf-8", errors="replace"))
        if raw_vtt.exists()
        else proportional_word_timings(script_text, dur)
    )
    return SynthesizedTrack(
        audio_path=trimmed_wav,
        duration_s=dur,
        word_timings=timings,
        applied_atempo=1.0,
        provider="edge",
    )

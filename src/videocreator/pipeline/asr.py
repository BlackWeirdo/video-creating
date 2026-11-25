"""ASR speech-segment extraction via Faster-Whisper CPU, SRT/VTT sidecars, or FFmpeg silence detection."""
from __future__ import annotations

import gc
import logging
import re
from pathlib import Path
from typing import Any

from videocreator.ai_models.catalog import get_local_model
from videocreator.paths import AppPaths
from videocreator.pipeline.audio_sep import probe_audio_channels
from videocreator.pipeline.ffmpeg import run_ffmpeg
from videocreator.pipeline.probe import probe_duration

logger = logging.getLogger("videocreator.pipeline.asr")

_SILENCE_START_RE = re.compile(r"silence_start:\s*([0-9]+(?:\.[0-9]+)?)")
_SILENCE_END_RE = re.compile(r"silence_end:\s*([0-9]+(?:\.[0-9]+)?)")
_SRT_TIME_RE = re.compile(
    r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})"
)


def parse_srt_segments(raw_srt: str) -> list[dict[str, Any]]:
    blocks = re.split(r"\r?\n\r?\n+", raw_srt.strip())
    segments: list[dict[str, Any]] = []
    for block in blocks:
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        m = _SRT_TIME_RE.search("\n".join(lines[:2]))
        if not m:
            continue
        h1, m1, s1, ms1, h2, m2, s2, ms2 = (int(g) for g in m.groups())
        start_s = h1 * 3600 + m1 * 60 + s1 + ms1 / 1000.0
        end_s = h2 * 3600 + m2 * 60 + s2 + ms2 / 1000.0
        text_lines = [ln for ln in lines if not ln.isdigit() and "-->" not in ln]
        source_text = " ".join(text_lines).strip()
        if end_s > start_s + 0.1 and source_text:
            segments.append(
                {
                    "index": len(segments),
                    "start_s": round(start_s, 3),
                    "end_s": round(end_s, 3),
                    "source_text": source_text,
                }
            )
    return segments


def transcribe_media_segments(
    paths: AppPaths,
    input_media: Path,
    *,
    lang: str = "auto",
    whisper_size: str = "small",
) -> list[dict[str, Any]]:
    """Extracts timed speech segments (with word timestamps) using faster-whisper, SRT sidecars, or silencedetect."""
    preferred_ids = (
        ["faster_whisper_medium", "faster_whisper_small"]
        if (whisper_size or "").strip().lower() == "medium"
        else ["faster_whisper_small", "faster_whisper_medium"]
    )
    model_info = None
    for mid in preferred_ids:
        try:
            cand = get_local_model(paths, mid)
        except Exception:
            cand = None
        if cand and cand.get("status") == "ready" and cand.get("installed_on_disk"):
            model_info = cand
            break

    if model_info is not None:
        try:
            from faster_whisper import WhisperModel

            w_path = Path(model_info["local_path"])
            w_dir = w_path if w_path.is_dir() else w_path.parent
            w_model = WhisperModel(str(w_dir), device="cpu", compute_type="int8", cpu_threads=4)
            try:
                lang_arg = None if lang == "auto" else lang
                w_segs, _ = w_model.transcribe(
                    str(input_media),
                    language=lang_arg,
                    word_timestamps=True,
                    vad_filter=True,
                )
                results: list[dict[str, Any]] = []
                for seg in w_segs:
                    txt = str(getattr(seg, "text", "") or "").strip()
                    st = float(getattr(seg, "start", 0.0))
                    en = float(getattr(seg, "end", st + 0.5))
                    words_raw = getattr(seg, "words", None) or []
                    words_list = [
                        {
                            "word": str(getattr(w, "word", "") or "").strip(),
                            "start_s": round(float(getattr(w, "start", st)), 3),
                            "end_s": round(float(getattr(w, "end", en)), 3),
                        }
                        for w in words_raw
                        if str(getattr(w, "word", "") or "").strip()
                    ]
                    if txt and en > st:
                        results.append(
                            {
                                "index": len(results),
                                "start_s": round(st, 3),
                                "end_s": round(en, 3),
                                "source_text": txt,
                                "words": words_list,
                            }
                        )
                if results:
                    return results
            finally:
                del w_model
                gc.collect()
        except Exception as exc:
            logger.debug("faster-whisper fallback triggered for %s: %s", input_media.name, exc)

    for ext in (".srt", ".vtt"):
        sidecar = input_media.with_suffix(ext)
        if sidecar.exists():
            parsed = parse_srt_segments(sidecar.read_text(encoding="utf-8", errors="replace"))
            if parsed:
                return parsed

    total_dur = max(0.8, probe_duration(input_media))
    channels = probe_audio_channels(input_media)
    silences: list[tuple[float, float]] = []
    if channels > 0:
        try:
            stderr_out = run_ffmpeg(
                [
                    "-i",
                    str(input_media.resolve()),
                    "-vn",
                    "-af",
                    "silencedetect=noise=-35dB:d=0.35",
                    "-f",
                    "null",
                    "-",
                ],
                allow_creative_filters=True,
            )
            cur_start: float | None = None
            for line in stderr_out.splitlines():
                ms = _SILENCE_START_RE.search(line)
                if ms:
                    cur_start = float(ms.group(1))
                    continue
                me = _SILENCE_END_RE.search(line)
                if me and cur_start is not None:
                    silences.append((cur_start, float(me.group(1))))
                    cur_start = None
            if cur_start is not None:
                silences.append((cur_start, total_dur))
        except Exception:
            silences = []

    windows: list[tuple[float, float]] = []
    cursor = 0.0
    for s_start, s_end in silences:
        if s_start - cursor >= 0.45:
            windows.append((cursor, min(total_dur, s_start)))
        cursor = max(cursor, s_end)
    if total_dur - cursor >= 0.45:
        windows.append((cursor, total_dur))

    if not windows:
        chunk_s = 3.0 if total_dur > 4.0 else total_dur
        t = 0.0
        while t < total_dur - 0.2:
            nxt = min(total_dur, t + chunk_s)
            if nxt - t >= 0.4:
                windows.append((t, nxt))
            t = nxt

    return [
        {
            "index": idx,
            "start_s": round(st, 3),
            "end_s": round(en, 3),
            "source_text": f"Segment {idx + 1} ({round(st, 1)}s-{round(en, 1)}s)",
        }
        for idx, (st, en) in enumerate(windows)
    ]

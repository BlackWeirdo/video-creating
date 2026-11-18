"""Shot boundary detection via rea-video CLI (Branch A, S1 verified) and span normalization."""
from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from videocreator.paths import find_ffmpeg_binary, find_rea_video_binary

MIN_SHOT_DURATION_S = 0.7
MAX_SHOT_DURATION_S = 8.0
TARGET_SPLIT_DURATION_S = 4.0


class ShotDetectionError(RuntimeError):
    """Raised when shot detection fails."""


@dataclass(frozen=True)
class ShotSpan:
    start_s: float
    end_s: float

    @property
    def duration_s(self) -> float:
        return round(self.end_s - self.start_s, 3)

    @property
    def midpoint_s(self) -> float:
        return round((self.start_s + self.end_s) / 2.0, 3)


def _split_long_span(span: ShotSpan, target_split_s: float, min_duration_s: float) -> list[ShotSpan]:
    """Splits a span into equal parts of about `target_split_s`; the last part ends exactly at the span end."""
    dur = span.end_s - span.start_s
    num_parts = max(2, math.ceil(dur / target_split_s))
    step = dur / num_parts
    parts: list[ShotSpan] = []
    for i in range(num_parts):
        seg_start = round(span.start_s + i * step, 3)
        seg_end = (
            round(span.end_s, 3)
            if i == num_parts - 1
            else round(span.start_s + (i + 1) * step, 3)
        )
        if seg_end - seg_start >= min_duration_s:
            parts.append(ShotSpan(start_s=seg_start, end_s=seg_end))
    return parts


def postprocess_shot_spans(
    raw_spans: list[ShotSpan],
    total_duration_s: float,
    *,
    min_duration_s: float = MIN_SHOT_DURATION_S,
    max_duration_s: float = MAX_SHOT_DURATION_S,
    target_split_s: float = TARGET_SPLIT_DURATION_S,
) -> list[ShotSpan]:
    """Applies FR-FTG-05 rules:
    - Clamps spans to [0, total_duration_s]
    - Drops shots shorter than 0.7s
    - Splits shots longer than 8.0s into equal 3–5s segments
    - Ensures at least 1 span if total_duration_s >= min_duration_s
    """
    filtered: list[ShotSpan] = []
    for span in raw_spans:
        start = max(0.0, min(span.start_s, total_duration_s))
        end = max(0.0, min(span.end_s, total_duration_s))
        if end - start >= min_duration_s:
            filtered.append(ShotSpan(start_s=round(start, 3), end_s=round(end, 3)))

    if not filtered and total_duration_s >= min_duration_s:
        filtered = [ShotSpan(start_s=0.0, end_s=round(total_duration_s, 3))]

    filtered.sort(key=lambda s: (s.start_s, s.end_s))

    non_overlapping: list[ShotSpan] = []
    cursor = 0.0
    for span in filtered:
        start = max(span.start_s, cursor)
        end = span.end_s
        if end - start >= min_duration_s:
            non_overlapping.append(ShotSpan(start_s=round(start, 3), end_s=round(end, 3)))
            cursor = end

    result: list[ShotSpan] = []
    for span in non_overlapping:
        if span.end_s - span.start_s > max_duration_s:
            result.extend(_split_long_span(span, target_split_s, min_duration_s))
        else:
            result.append(span)

    return result


def _detect_shots_ffmpeg(
    video_path: Path,
    *,
    ffmpeg_bin: str,
    total_duration_s: float,
    timeout_s: float,
) -> tuple[list[ShotSpan], str]:
    """Fallback shot boundary detector using FFmpeg's scene score filter (`FR-FTG-05`, `S1`)."""
    import re

    cmd = [
        ffmpeg_bin,
        "-hide_banner",
        "-i",
        str(video_path),
        "-vf",
        "select='gt(scene,0.32)',showinfo",
        "-an",
        "-f",
        "null",
        "-",
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired as exc:
        raise ShotDetectionError(f"ffmpeg scene detection timed out after {timeout_s}s") from exc

    combined_log = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()[-2000:]
    if proc.returncode != 0:
        raise ShotDetectionError(f"ffmpeg scene detection failed (exit {proc.returncode}): {combined_log[-500:]}")

    cut_times = sorted(
        {
            round(float(m.group(1)), 3)
            for m in re.finditer(r"pts_time:\s*([0-9]+(?:\.[0-9]+)?)", proc.stderr or "")
            if 0.0 < float(m.group(1)) < total_duration_s
        }
    )
    boundaries = [0.0, *cut_times, round(total_duration_s, 3)]
    raw_spans = [
        ShotSpan(start_s=boundaries[i], end_s=boundaries[i + 1])
        for i in range(len(boundaries) - 1)
        if boundaries[i + 1] > boundaries[i]
    ]
    return postprocess_shot_spans(raw_spans, total_duration_s), f"[ffmpeg-scene-fallback]\n{combined_log}"


def detect_shots(
    video_path: Path,
    *,
    total_duration_s: float,
    work_dir: Path | None = None,
    timeout_s: float = 300.0,
) -> tuple[list[ShotSpan], str]:
    """Runs `rea-video decompose` (Branch A) to detect shot boundaries and normalizes them,
    falling back to FFmpeg scene detection when `rea-video` is not installed.

    Returns (spans, stderr_or_stdout_tail).
    """
    if not video_path.exists():
        raise ShotDetectionError(f"Footage file not found: {video_path}")

    ffmpeg_raw = find_ffmpeg_binary("ffmpeg")
    ffmpeg_path = Path(ffmpeg_raw)
    try:
        rea_bin = find_rea_video_binary()
    except FileNotFoundError:
        return _detect_shots_ffmpeg(
            video_path,
            ffmpeg_bin=ffmpeg_raw,
            total_duration_s=total_duration_s,
            timeout_s=timeout_s,
        )

    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    if ffmpeg_path.is_Absolute() if hasattr(ffmpeg_path, "is_Absolute") else ffmpeg_path.is_absolute():
        if ffmpeg_path.parent.exists():
            env["PATH"] = f"{ffmpeg_path.parent}{os.pathsep}{env.get('PATH', '')}"

    cleanup_dir = False
    if work_dir is None:
        out_dir = Path(tempfile.mkdtemp(prefix="vc-rea-shots-"))
        cleanup_dir = True
    else:
        out_dir = work_dir
        out_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        rea_bin,
        "decompose",
        str(video_path),
        "-o",
        str(out_dir),
        "--no-packaging",
        "--no-vlm",
        "--no-asr",
        "--no-ocr",
        "--no-stems",
        "--no-speakers",
        "--lang",
        "en",
    ]
    try:
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                timeout=timeout_s,
                stdin=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired as exc:
            raise ShotDetectionError(
                f"rea-video decompose timed out after {timeout_s}s"
            ) from exc

        combined_log = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()[-2000:]
        breakdown_file = out_dir / "breakdown.json"
        if proc.returncode != 0 or not breakdown_file.exists():
            raise ShotDetectionError(
                f"rea-video decompose failed (exit {proc.returncode}): {combined_log[-500:]}"
            )

        data = json.loads(breakdown_file.read_text(encoding="utf-8"))
        raw_shots = data.get("shots") or []
        raw_spans: list[ShotSpan] = []
        for s in raw_shots:
            start = float(s.get("start", 0.0))
            end = float(s.get("end", 0.0))
            if end > start:
                raw_spans.append(ShotSpan(start_s=start, end_s=end))

        spans = postprocess_shot_spans(raw_spans, total_duration_s)
        return spans, combined_log
    finally:
        if cleanup_dir:
            shutil.rmtree(out_dir, ignore_errors=True)

"""Midpoint thumbnail extraction for shots via FFmpeg."""
from __future__ import annotations

import subprocess
from pathlib import Path

from videocreator.paths import find_ffmpeg_binary


class ThumbnailError(RuntimeError):
    """Raised when FFmpeg fails to extract a shot thumbnail."""


def extract_thumbnail(
    video_path: Path,
    timestamp_s: float,
    out_jpg: Path,
    timeout_s: float = 30.0,
) -> Path:
    out_jpg.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg_bin = find_ffmpeg_binary("ffmpeg")
    seek_s = max(0.0, round(timestamp_s, 3))
    cmd = [
        ffmpeg_bin,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        f"{seek_s:.3f}",
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        "-q:v",
        "3",
        "-update",
        "1",
        str(out_jpg),
    ]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_s,
        stdin=subprocess.DEVNULL,
    )
    if proc.returncode != 0 or not out_jpg.exists():
        stderr_tail = (proc.stderr or "").strip()[-500:]
        raise ThumbnailError(
            f"Failed to extract thumbnail at {seek_s}s (code {proc.returncode}): {stderr_tail}"
        )
    return out_jpg

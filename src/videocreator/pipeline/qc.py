"""Automated FFmpeg post-render Quality Control (`blackdetect`, `freezedetect`, `silencedetect`, `ebur128`)."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from videocreator.paths import find_ffmpeg_binary
from videocreator.pipeline.probe import probe_video

_BLACK_DUR_RE = re.compile(r"black_duration:\s*([\d.]+)")
_FREEZE_DUR_RE = re.compile(r"freeze_duration:\s*([\d.]+)")
_SILENCE_DUR_RE = re.compile(r"silence_duration:\s*([\d.]+)")
_SILENCE_START_RE = re.compile(r"silence_start:\s*([\d.]+)")
_LUFS_RE = re.compile(r"\bI:\s*(-?[\d.]+)\s+LUFS")
_TRUE_PEAK_RE = re.compile(r"\bPeak:\s*(-?[\d.]+)\s+dBFS")


def run_video_qc(video_path: Path, *, expect_voice: bool = False) -> dict[str, Any]:
    """Inspects rendered MP4 with FFmpeg detection filters and returns structured QC report."""
    if not video_path.exists():
        return {
            "passed": False,
            "duration_s": 0.0,
            "black_duration_s": 0.0,
            "freeze_duration_s": 0.0,
            "silence_duration_s": 0.0,
            "integrated_lufs": None,
            "true_peak_dbfs": None,
            "issues": [f"Không tìm thấy file thành phẩm: {video_path.name}"],
        }

    info = probe_video(video_path)
    issues: list[str] = []
    if info.width <= 0 or info.height <= 0:
        issues.append("Video thiếu stream hình hợp lệ")
    if not info.has_audio:
        issues.append("Video thiếu track âm thanh")

    ffmpeg_bin = find_ffmpeg_binary("ffmpeg")
    cmd = [
        ffmpeg_bin,
        "-hide_banner",
        "-i",
        str(video_path.resolve()),
        "-vf",
        "blackdetect=d=0.4:pix_th=0.10,freezedetect=n=-60dB:d=1.5",
    ]
    if info.has_audio:
        cmd.extend(["-af", "silencedetect=n=-50dB:d=1.2,ebur128=peak=true"])
    cmd.extend(["-f", "null", "-"])

    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=90,
        check=False,
    )
    stderr = proc.stderr or ""
    if proc.returncode != 0:
        issues.append(f"FFmpeg QC lỗi exit={proc.returncode}")

    black_durs = [float(m.group(1)) for m in _BLACK_DUR_RE.finditer(stderr)]
    freeze_durs = [float(m.group(1)) for m in _FREEZE_DUR_RE.finditer(stderr)]
    silence_durs = [float(m.group(1)) for m in _SILENCE_DUR_RE.finditer(stderr)]

    # If silence started near the start and ran to EOF without closing silence_duration
    if not silence_durs and _SILENCE_START_RE.search(stderr):
        starts = [float(m.group(1)) for m in _SILENCE_START_RE.finditer(stderr)]
        if starts:
            silence_durs.append(max(0.0, info.duration_s - starts[-1]))

    black_total = round(sum(black_durs), 3)
    freeze_total = round(sum(freeze_durs), 3)
    silence_total = round(sum(silence_durs), 3)

    lufs_matches = _LUFS_RE.findall(stderr)
    peak_matches = _TRUE_PEAK_RE.findall(stderr)
    integrated_lufs = float(lufs_matches[-1]) if lufs_matches else None
    true_peak_dbfs = float(peak_matches[-1]) if peak_matches else None

    dur = max(0.5, info.duration_s)
    if (dur >= 2.0 and black_total >= 0.8) or (black_total / dur) > 0.25:
        issues.append(f"Phát hiện khung hình đen kéo dài {black_total:.2f}s")
    if (dur >= 4.0 and freeze_total / dur) > 0.75:
        issues.append(f"Hình ảnh bị đứng tĩnh kéo dài {freeze_total:.2f}s")
    if expect_voice and ((silence_total / dur) > 0.80 or (integrated_lufs is not None and integrated_lufs < -45.0)):
        issues.append(
            f"Âm thanh giọng đọc quá nhỏ hoặc bị câm (silence={silence_total:.2f}s, LUFS={integrated_lufs})"
        )

    return {
        "passed": len(issues) == 0,
        "duration_s": round(info.duration_s, 3),
        "black_duration_s": black_total,
        "freeze_duration_s": freeze_total,
        "silence_duration_s": silence_total,
        "integrated_lufs": integrated_lufs,
        "true_peak_dbfs": true_peak_dbfs,
        "issues": issues,
    }

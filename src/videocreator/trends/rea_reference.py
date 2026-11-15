"""rea-video decomposition of a downloaded reference video, with its on-disk cache."""
from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

from videocreator.paths import find_ffmpeg_binary, find_rea_video_binary

logger = logging.getLogger("videocreator.trends.analyse")

REA_DECOMPOSE_TIMEOUT_S = 1800


def _has_full_rea_cache(out_dir: Path) -> bool:
    """True if `out_dir` contains full-pass markers (`stems/` or `packaging` in `breakdown.json`)."""
    if (out_dir / "stems").exists():
        return True
    bd = out_dir / "breakdown.json"
    if bd.is_file():
        try:
            data = json.loads(bd.read_text(encoding="utf-8", errors="replace"))
            return isinstance(data, dict) and "packaging" in data
        except Exception:
            return False
    return False


def _read_rea_outputs(out_dir: Path) -> dict[str, Any]:
    """Reads `VIDEO.md`, `timeline.md`, and `*storyboard*.jpg` from `out_dir` if present."""
    video_md = ""
    timeline_md = ""
    storyboard: Path | None = None
    for candidate in out_dir.rglob("VIDEO.md"):
        video_md = candidate.read_text(encoding="utf-8", errors="replace")[:4000]
        break
    for candidate in out_dir.rglob("timeline.md"):
        timeline_md = candidate.read_text(encoding="utf-8", errors="replace")[:4000]
        break
    for candidate in out_dir.rglob("*storyboard*.jpg"):
        storyboard = candidate
        break

    return {
        "video_md": video_md,
        "timeline_md": timeline_md,
        "storyboard": storyboard,
    }


def run_rea_decompose_reference(
    video_path: Path, out_dir: Path
) -> dict[str, Any]:
    """Runs full `rea-video decompose` (without `--vlm`) on a reference video and reads `VIDEO.md` / `timeline.md`."""
    out_dir.mkdir(parents=True, exist_ok=True)
    cached = _read_rea_outputs(out_dir)
    if cached["video_md"].strip() and cached["timeline_md"].strip() and _has_full_rea_cache(out_dir):
        return cached

    try:
        rea_bin = find_rea_video_binary()
        ffmpeg_dir = str(Path(find_ffmpeg_binary("ffmpeg")).parent)
        env = dict(os.environ)
        env["PATH"] = f"{ffmpeg_dir}{os.pathsep}{env.get('PATH', '')}"
        env["PYTHONIOENCODING"] = "utf-8"

        # Flags verified against the installed CLI (spike S1): full breakdown (stems, packaging, OCR, ASR, shots) without VLM.
        proc = subprocess.run(
            [rea_bin, "decompose", str(video_path), "-o", str(out_dir), "--no-vlm", "--lang", "en"],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=REA_DECOMPOSE_TIMEOUT_S,
            check=False,
        )
        if proc.returncode != 0:
            logger.warning(
                "rea-video decompose exited %d on %s: %s",
                proc.returncode, video_path.name, ((proc.stderr or "") + (proc.stdout or ""))[-400:],
            )
    except Exception as exc:
        logger.warning("rea-video decompose failed on %s: %s", video_path, exc)

    return _read_rea_outputs(out_dir)

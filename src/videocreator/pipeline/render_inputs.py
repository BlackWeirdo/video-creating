"""Inputs of a render: the 9:16 filter of a source shot and the background music pick."""
from __future__ import annotations

import random
from pathlib import Path
from typing import Any

from videocreator.db import query_all, query_one
from videocreator.paths import AppPaths


def build_segment_filter_args(
    *,
    orientation: str,
    width: int,
    height: int,
    crop_cfg: dict[str, Any] | None,
) -> list[str]:
    """Builds `-vf` or `-filter_complex` arguments to convert a source shot to 1080x1920 30fps without violating BR-PRD-03."""
    if orientation == "landscape" and width > 0 and height > 0:
        mode = str((crop_cfg or {}).get("mode") or "blur_pad")
        if mode == "crop":
            x_ratio = max(0.0, min(1.0, float((crop_cfg or {}).get("x_offset_ratio", 0.5))))
            crop_w = int(round(height * 9 / 16))
            crop_w = max(2, crop_w - (crop_w % 2))
            crop_w = min(width, crop_w)
            max_x = max(0, width - crop_w)
            x_off = int(round(max_x * x_ratio))
            vf = f"crop={crop_w}:{height}:{x_off}:0,scale=1080:1920,setsar=1,fps=30"
            return ["-vf", vf]

        # Default landscape handling: full frame centered on a blurred 9:16 background (never center-cropped)
        fc = (
            "split[bg][fg];"
            "[bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=20:5[bgb];"
            "[fg]scale=1080:1920:force_original_aspect_ratio=decrease[fgs];"
            "[bgb][fgs]overlay=(W-w)/2:(H-h)/2,setsar=1,fps=30"
        )
        return ["-filter_complex", fc]

    vf = (
        "scale=1080:1920:force_original_aspect_ratio=decrease,"
        "pad=1080:1920:(ow-iw)/2:(oh-ih)/2,"
        "setsar=1,"
        "fps=30"
    )
    return ["-vf", vf]


def pick_music_asset(paths: AppPaths, music_asset_id: int | None = None) -> Path | None:
    if music_asset_id is not None:
        row = query_one(
            paths.db_file,
            "SELECT path FROM assets WHERE id = ? AND kind = 'music'",
            (music_asset_id,),
        )
        if row and row.get("path"):
            p = paths.media_dir / str(row["path"])
            if p.exists():
                return p
    rows = query_all(paths.db_file, "SELECT path FROM assets WHERE kind = 'music' ORDER BY id ASC")
    valid_paths = [paths.media_dir / str(r["path"]) for r in rows if r.get("path") and (paths.media_dir / str(r["path"])).exists()]
    if not valid_paths:
        return None
    return random.choice(valid_paths)

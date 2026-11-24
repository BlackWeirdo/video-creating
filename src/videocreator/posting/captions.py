"""Per-platform caption text of a video and the manual-posting bundle built from it."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

from videocreator.db import query_one
from videocreator.paths import AppPaths


def format_platform_caption(video_row: dict[str, Any], platform: str) -> str:
    """Extracts the platform-specific caption text + hashtags from `videos.captions_json` merged over `plan_json`."""
    plan_caps: dict[str, Any] = {}
    if video_row.get("plan_json"):
        try:
            raw_plan_caps = json.loads(str(video_row["plan_json"])).get("captions")
            if isinstance(raw_plan_caps, dict):
                plan_caps = raw_plan_caps
        except Exception:
            plan_caps = {}

    override_caps: dict[str, Any] = {}
    if video_row.get("captions_json"):
        try:
            raw_override = json.loads(str(video_row["captions_json"]))
            if isinstance(raw_override, dict):
                override_caps = raw_override
        except Exception:
            override_caps = {}

    captions = {**plan_caps, **override_caps}
    plat_obj = captions.get(platform)
    if (not isinstance(plat_obj, dict) or not str(plat_obj.get("text") or "").strip()) and platform == "youtube":
        plat_obj = captions.get("tiktok") or captions.get("facebook") or {}
    if not isinstance(plat_obj, dict):
        plat_obj = {}
    text = str(plat_obj.get("text") or "").strip()
    tags = [str(t).strip() for t in (plat_obj.get("hashtags") or []) if str(t).strip()]
    if tags:
        return f"{text}\n\n{' '.join(tags)}".strip()
    return text


def build_manual_bundle_zip(paths: AppPaths, video_id: int) -> Path:
    """Builds a downloadable `.zip` containing the rendered MP4, cover image, and 4 platform captions."""
    v_row = query_one(paths.db_file, "SELECT * FROM videos WHERE id = ?", (video_id,))
    if v_row is None or not v_row.get("output_path"):
        raise LookupError(f"Rendered video #{video_id} not found")

    mp4_path = paths.media_dir / str(v_row["output_path"])
    if not mp4_path.exists():
        raise FileNotFoundError(f"Video file not found on disk: {mp4_path}")

    zip_path = paths.work_dir / f"manual_bundle_video_{video_id}.zip"
    zip_path.parent.mkdir(parents=True, exist_ok=True)

    caption_lines = [f"=== PACK ĐĂNG TAY VIDEO #{video_id} ===", ""]
    for plat in ("facebook", "instagram", "threads", "tiktok"):
        caption_lines.append(f"--- {plat.upper()} ---")
        caption_lines.append(format_platform_caption(v_row, plat))
        caption_lines.append("")

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(mp4_path, arcname=f"video_{video_id}.mp4")
        if v_row.get("cover_path"):
            cov = paths.media_dir / str(v_row["cover_path"])
            if cov.exists():
                ext = cov.suffix.lower() or ".jpg"
                zf.write(cov, arcname=f"cover_{video_id}{ext}")
        zf.writestr("captions.txt", "\n".join(caption_lines))

    return zip_path

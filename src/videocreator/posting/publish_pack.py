"""5-platform `.zip` Publish Pack builder: master MP4, titled cover JPEG, captions.txt, metadata.json."""
from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path
from typing import Any

from videocreator.db import query_one
from videocreator.jsonutil import loads_or
from videocreator.paths import AppPaths
from videocreator.pipeline.export import extract_cover_frame
from videocreator.pipeline.ffmpeg import run_ffmpeg
from videocreator.pipeline.probe import probe_video
from videocreator.pipeline.subtitles import FONTS_DIR, SubtitleEvent, build_ass
from videocreator.posting.captions import format_platform_caption

PUBLISH_PACK_PLATFORMS: tuple[str, ...] = (
    "facebook",
    "instagram",
    "threads",
    "tiktok",
    "youtube",
)


def _render_titled_cover_jpg(
    src_cover: Path,
    dest_cover: Path,
    title_text: str,
    work_dir: Path,
) -> Path:
    """Burns a clean Vietnamese headline overlay onto `src_cover` via FFmpeg libass."""
    clean_title = title_text.strip()
    if not clean_title or not src_cover.exists():
        return src_cover
    try:
        info = probe_video(src_cover)
        w = info.width if info.width > 0 else 1080
        h = info.height if info.height > 0 else 1920
    except Exception:
        w, h = 1080, 1920

    ass_doc = build_ass(
        [SubtitleEvent(start_s=0.0, end_s=2.0, text=clean_title)],
        play_res_x=w,
        play_res_y=h,
        safe_top_ratio=0.14,
        safe_bottom_ratio=0.18,
        safe_right_ratio=0.10,
        font_size=max(42, min(68, int(round(w * 0.056)))),
        layout_preset="top_banner",
    )
    cover_work = work_dir / "cover_overlay"
    cover_work.mkdir(parents=True, exist_ok=True)
    (cover_work / "cover.ass").write_text(ass_doc, encoding="utf-8")
    shutil.copytree(FONTS_DIR, cover_work / "fonts", dirs_exist_ok=True)
    try:
        run_ffmpeg(
            [
                "-i",
                str(src_cover.resolve()),
                "-vf",
                "subtitles=cover.ass:fontsdir=fonts",
                "-frames:v",
                "1",
                "-q:v",
                "3",
                str(dest_cover.resolve()),
            ],
            cwd=cover_work,
        )
        return dest_cover if dest_cover.exists() else src_cover
    except Exception:
        return src_cover


def build_publish_pack_zip(
    paths: AppPaths,
    video_id: int,
    *,
    cover_title: str | None = None,
) -> Path:
    """Packages master MP4, titled cover image, 5-platform `captions.txt`, and `metadata.json` into a `.zip`."""
    v_row = query_one(paths.db_file, "SELECT * FROM videos WHERE id = ?", (video_id,))
    if v_row is None or not v_row.get("output_path"):
        raise LookupError(f"Rendered video #{video_id} not found")

    mp4_path = paths.media_dir / str(v_row["output_path"])
    if not mp4_path.exists():
        raise FileNotFoundError(f"Video file not found on disk: {mp4_path}")

    plan = loads_or(v_row.get("plan_json"), {})
    if not isinstance(plan, dict):
        plan = {}
    title_to_burn = (
        cover_title.strip()
        if cover_title is not None
        else str(plan.get("title") or "").strip()
    )

    pack_work = paths.work_dir / f"pack_work_{video_id}"
    if pack_work.exists():
        shutil.rmtree(pack_work, ignore_errors=True)
    pack_work.mkdir(parents=True, exist_ok=True)

    try:
        base_cover = (
            paths.media_dir / str(v_row["cover_path"])
            if v_row.get("cover_path")
            else pack_work / "base_cover.jpg"
        )
        if not base_cover.exists():
            base_cover = extract_cover_frame(mp4_path, pack_work / "base_cover.jpg", at_s=1.0)

        final_cover = (
            _render_titled_cover_jpg(
                base_cover, pack_work / "titled_cover.jpg", title_to_burn, pack_work
            )
            if title_to_burn
            else base_cover
        )

        caption_lines = [f"=== PUBLISH PACK VIDEO #{video_id} ===", ""]
        captions_map: dict[str, str] = {}
        for plat in PUBLISH_PACK_PLATFORMS:
            text_for_plat = format_platform_caption(v_row, plat)
            captions_map[plat] = text_for_plat
            caption_lines.append(f"--- {plat.upper()} ---")
            caption_lines.append(text_for_plat)
            caption_lines.append("")

        metadata: dict[str, Any] = {
            "video_id": int(video_id),
            "workspace_id": int(v_row.get("workspace_id") or 1),
            "title": str(plan.get("title") or ""),
            "aspect_ratio": str(v_row.get("aspect_ratio") or "9:16"),
            "style_preset": str(v_row.get("style_preset") or "tiktok_karaoke"),
            "duration_s": v_row.get("duration_s"),
            "qc": loads_or(v_row.get("qc_json"), {}),
            "captions": captions_map,
        }

        zip_path = paths.work_dir / f"publish_pack_video_{video_id}.zip"
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.write(mp4_path, arcname=f"video_{video_id}.mp4")
            if final_cover.exists():
                ext = final_cover.suffix.lower() or ".jpg"
                zf.write(final_cover, arcname=f"cover_{video_id}{ext}")
            zf.writestr("captions.txt", "\n".join(caption_lines))
            zf.writestr(
                "metadata.json", json.dumps(metadata, ensure_ascii=False, indent=2)
            )
        return zip_path
    finally:
        shutil.rmtree(pack_work, ignore_errors=True)

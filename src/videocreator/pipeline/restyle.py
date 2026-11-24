"""Fast Video Restyle: swaps style preset / music / SFX reusing cached cut video and voice WAV."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from videocreator.db import get_conn, query_one, record_audit
from videocreator.jsonutil import loads_or
from videocreator.paths import AppPaths
from videocreator.pipeline.render import finalize_master_export, render_video
from videocreator.pipeline.render_inputs import pick_music_asset_record
from videocreator.pipeline.render_steps import subtitle_events_from_json
from videocreator.pipeline.styles import get_style_preset


def restyle_video(
    paths: AppPaths,
    video_id: int,
    style_preset_id: str | None = None,
    *,
    music_asset_id: int | None = None,
    preset: str = "veryfast",
) -> str:
    """Re-renders subtitles, audio ducking, and cover using a new style preset without re-cutting or re-synthesizing voice."""
    v_row = query_one(paths.db_file, "SELECT * FROM videos WHERE id = ?", (video_id,))
    if v_row is None:
        raise LookupError(f"Video #{video_id} not found")

    chosen_id = (style_preset_id or v_row.get("style_preset") or "tiktok_karaoke").strip()
    style_row = get_style_preset(paths.db_file, chosen_id)
    if style_row is None:
        raise ValueError(f"Style preset '{chosen_id}' does not exist")

    cache = loads_or(v_row.get("render_cache_json"), {})
    if not isinstance(cache, dict):
        cache = {}
    cut_rel = str(cache.get("cut_mp4") or "")
    subs_rel = str(cache.get("sub_events_file") or "")
    cut_mp4 = (paths.media_dir / cut_rel) if cut_rel else None
    subs_file = (paths.media_dir / subs_rel) if subs_rel else None

    if cut_mp4 is None or not cut_mp4.exists() or subs_file is None or not subs_file.exists():
        # Cache missing -> stamp new style preset and perform full render
        with get_conn(paths.db_file) as conn:
            conn.execute(
                "UPDATE videos SET style_preset = ? WHERE id = ?",
                (style_row["id"], video_id),
            )
        return render_video(
            paths,
            video_id,
            preset=preset,
            music_asset_id=music_asset_id,
        )

    voice_rel = str(cache.get("voice_wav") or "")
    voice_path = (paths.media_dir / voice_rel) if voice_rel else None
    if voice_path is not None and not voice_path.exists():
        voice_path = None

    sub_items = json.loads(subs_file.read_text(encoding="utf-8"))
    sub_events = subtitle_events_from_json(sub_items if isinstance(sub_items, list) else [])

    effective_music_id = (
        music_asset_id if music_asset_id is not None else cache.get("music_asset_id")
    )
    music_rec = (
        pick_music_asset_record(paths, music_asset_id=int(effective_music_id))
        if effective_music_id is not None
        else pick_music_asset_record(paths)
    )
    music_path = music_rec["path"] if music_rec is not None else None
    aspect_ratio = str(v_row.get("aspect_ratio") or cache.get("aspect_ratio") or "9:16")
    cut_times = [float(t) for t in (cache.get("cut_times_s") or [])]
    mix_src = bool(cache.get("mix_source_audio"))

    work_dir = paths.work_dir / f"restyle_{video_id}"
    if work_dir.exists():
        shutil.rmtree(work_dir, ignore_errors=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    try:
        rel_out, rel_cover, actual_duration_s, preflight_map, qc_report = finalize_master_export(
            paths,
            video_id=video_id,
            cut_mp4=cut_mp4,
            work_dir=work_dir,
            sub_events=sub_events,
            style_row=style_row,
            aspect_ratio=aspect_ratio,
            music_path=music_path,
            voice_path=voice_path,
            cut_times_s=cut_times,
            mix_source_audio=mix_src,
            preset=preset,
        )
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    with get_conn(paths.db_file) as conn:
        conn.execute(
            """
            UPDATE videos
            SET output_path = ?,
                cover_path = ?,
                duration_s = ?,
                preflight_json = ?,
                qc_json = ?,
                style_preset = ?,
                error = NULL
            WHERE id = ?
            """,
            (
                rel_out,
                rel_cover,
                round(actual_duration_s, 3),
                json.dumps(preflight_map, ensure_ascii=False),
                json.dumps(qc_report, ensure_ascii=False),
                style_row["id"],
                video_id,
            ),
        )
        record_audit(
            conn,
            actor="worker",
            action="video.restyled",
            object_type="video",
            object_id=video_id,
            detail=f"style={style_row['id']}, duration={actual_duration_s:.2f}s",
        )
    return f"Restyled video #{video_id} with '{style_row['id']}' ({actual_duration_s:.2f}s)"


def run_restyle_job(paths: AppPaths, video_id: int) -> str:
    return restyle_video(paths, video_id)

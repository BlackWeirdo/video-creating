"""5-step FFmpeg 9:16 renderer with ASS subtitles, landscape blur-pad/crop, music mix, and preflight (Phase 05)."""
from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any

from videocreator.config import load_settings
from videocreator.db import get_conn, query_one, record_audit
from videocreator.paths import AppPaths
from videocreator.pipeline.export import extract_cover_frame, normalize_to_master
from videocreator.pipeline.ffmpeg import RenderError
from videocreator.pipeline.preflight import check_all_platforms
from videocreator.pipeline.render_inputs import pick_music_asset
from videocreator.pipeline.render_status import claim_for_render, score_or_send_to_approval
from videocreator.pipeline.render_steps import (
    SUBTITLE_FILENAME,
    add_voice_over,
    concat_segments,
    cut_shot_segments,
    write_subtitle_file,
)
from videocreator.state import transition
from videocreator.tg.approval_notify import notify_pending

logger = logging.getLogger("videocreator.pipeline.render")


def _render_to_master(
    paths: AppPaths,
    video_row: dict[str, Any],
    work_dir: Path,
    *,
    preset: str,
    music_asset_id: int | None,
    mpt_client: Any,
) -> tuple[str, float]:
    """Runs the render steps and saves the output on the video row. Returns `(rel_out, duration_s)`."""
    video_id = int(video_row["id"])
    settings = load_settings(paths.config_file)
    try:
        plan = json.loads(video_row.get("plan_json") or "{}")
    except json.JSONDecodeError as exc:
        raise RenderError(f"Invalid plan_json on video #{video_id}: {exc}") from exc

    planned_shots = plan.get("shots") or []
    if not planned_shots:
        raise RenderError(f"Video #{video_id} plan has no shots")

    seg_files, sub_events, cut_duration_s = cut_shot_segments(paths, planned_shots, work_dir)
    cut_mp4 = concat_segments(seg_files, work_dir)

    engine_mode = str(video_row.get("engine") or "ffmpeg")
    voice_lang = str(video_row.get("voice_lang") or plan.get("voice_lang") or "none")
    voice_track = None
    if voice_lang in ("vi", "en") and (engine_mode == "mpt" or mpt_client is not None):
        voice_track, voice_sub_events = add_voice_over(
            paths,
            video_id,
            script_lines=[str(ps.get("text") or "") for ps in planned_shots],
            voice_lang=voice_lang,
            work_dir=work_dir,
            mpt_client=mpt_client,
            video_duration_s=cut_duration_s,
        )
        if voice_sub_events is not None:
            sub_events = voice_sub_events
    write_subtitle_file(sub_events, settings, work_dir)

    # Step 4: Burn ASS subtitles, mix music/silent track, and normalize to Master MP4 + cover.jpg
    rel_out = f"output/video_{video_id}.mp4"
    rel_cover = f"output/cover_{video_id}.jpg"
    abs_out = paths.media_dir / rel_out
    actual_duration_s = normalize_to_master(
        cut_mp4,
        abs_out,
        music_path=pick_music_asset(paths, music_asset_id=music_asset_id),
        voice_path=voice_track.audio_path if voice_track is not None else None,
        ass_filename=SUBTITLE_FILENAME if sub_events else None,
        cwd=work_dir,
        preset=preset,
        crf=18,
    )
    extract_cover_frame(abs_out, paths.media_dir / rel_cover, at_s=1.0)

    # Step 5: Run platform preflight checks
    preflight_map = check_all_platforms(abs_out, settings)

    transition(paths.db_file, video_id, "rendered", expected_from="rendering")
    with get_conn(paths.db_file) as conn:
        conn.execute(
            """
            UPDATE videos
            SET output_path = ?,
                cover_path = ?,
                duration_s = ?,
                preflight_json = ?,
                error = NULL
            WHERE id = ?
            """,
            (
                rel_out,
                rel_cover,
                round(actual_duration_s, 3),
                json.dumps(preflight_map, ensure_ascii=False),
                video_id,
            ),
        )
        record_audit(
            conn,
            actor="worker",
            action="video.rendered",
            object_type="video",
            object_id=video_id,
            detail=f"duration={actual_duration_s:.2f}s, out={rel_out}",
        )
    return rel_out, actual_duration_s


def render_video(
    paths: AppPaths,
    video_id: int,
    *,
    preset: str = "veryfast",
    music_asset_id: int | None = None,
    mpt_client: Any = None,
    auto_score: bool = False,
    score_provider: Any = None,
    score_override: float | None = None,
) -> str:
    """Executes the 5-step FFmpeg (or MPT + FFmpeg fallback) render pipeline for `video_id`."""
    video_row = query_one(paths.db_file, "SELECT * FROM videos WHERE id = ?", (video_id,))
    if video_row is None:
        raise LookupError(f"Video #{video_id} not found")
    claim_for_render(paths, video_id, str(video_row["status"]))

    work_dir = paths.work_dir / f"render_{video_id}"
    if work_dir.exists():
        shutil.rmtree(work_dir, ignore_errors=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    try:
        rel_out, actual_duration_s = _render_to_master(
            paths, video_row, work_dir, preset=preset, music_asset_id=music_asset_id, mpt_client=mpt_client
        )
        shutil.rmtree(work_dir, ignore_errors=True)

        should_score = (
            auto_score
            or score_provider is not None
            or score_override is not None
            or int(video_row.get("auto_render") or 0) == 1
        )
        final_status = score_or_send_to_approval(
            paths, video_id, should_score=should_score, score_provider=score_provider, score_override=score_override
        )
        if final_status == "pending_approval":
            try:
                notify_pending(paths, video_id)
            except Exception as tg_exc:
                logger.warning("notify_pending hook warning for video #%d: %s", video_id, tg_exc)
        return f"Rendered video #{video_id} ({actual_duration_s:.2f}s) -> {rel_out}"

    except Exception as exc:
        err_msg = str(exc)[:500]
        with get_conn(paths.db_file) as conn:
            conn.execute(
                "UPDATE videos SET status = 'failed', error = ? WHERE id = ?",
                (err_msg, video_id),
            )
        raise

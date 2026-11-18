"""5-step FFmpeg 9:16 renderer with ASS subtitles, landscape blur-pad/crop, music mix, and preflight (Phase 05)."""
from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any

from videocreator.config import load_settings
from videocreator.db import get_conn, query_all, query_one, record_audit
from videocreator.paths import AppPaths
from videocreator.pipeline.audio_beats import snap_shots_to_beats
from videocreator.pipeline.export import extract_cover_frame, normalize_to_master
from videocreator.pipeline.ffmpeg import RenderError
from videocreator.pipeline.preflight import check_all_platforms
from videocreator.pipeline.render_inputs import pick_music_asset_record
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
from videocreator.trends.suggestion_formula import load_suggestion_formula

logger = logging.getLogger("videocreator.pipeline.render")


def _load_trend_blueprint_for_render(paths: AppPaths, video_row: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    if isinstance(plan.get("trend_analysis"), dict) and plan["trend_analysis"]:
        return dict(plan["trend_analysis"])
    sug_id = video_row.get("suggestion_id")
    if sug_id:
        formula_obj = load_suggestion_formula(paths.db_file, int(sug_id)) or {}
        if isinstance(formula_obj.get("trend_analysis"), dict):
            return dict(formula_obj["trend_analysis"])
    return {}


def _load_shot_bounds(paths: AppPaths, planned_shots: list[dict[str, Any]]) -> dict[int, tuple[float, float]]:
    ids = sorted({int(s.get("shot_id") or 0) for s in planned_shots if int(s.get("shot_id") or 0) > 0})
    if not ids:
        return {}
    rows = query_all(
        paths.db_file,
        f"SELECT id, start_s, end_s FROM shots WHERE id IN ({','.join('?' * len(ids))})",
        ids,
    )
    return {int(r["id"]): (float(r["start_s"]), float(r["end_s"])) for r in rows}


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

    blueprint = _load_trend_blueprint_for_render(paths, video_row, plan)
    music_mood = str(blueprint.get("music_mood") or plan.get("music_mood") or "").strip() or None
    energy_level = str(blueprint.get("energy_level") or plan.get("energy_level") or "").strip() or None
    audio_mode = str(blueprint.get("audio_mode") or plan.get("audio_mode") or "").strip()
    hook_layout = str(blueprint.get("hook_layout") or plan.get("hook_layout") or "clean_bottom").strip()

    music_rec = pick_music_asset_record(
        paths,
        music_asset_id=music_asset_id,
        music_mood=music_mood,
        energy_level=energy_level,
    )
    row_vlang = str(video_row.get("voice_lang") or "")
    plan_vlang = str(plan.get("voice_lang") or "")
    voice_lang = row_vlang if row_vlang in ("vi", "en") else (plan_vlang or row_vlang or "none")

    want_beat_sync = bool(blueprint) or bool(plan.get("beat_sync"))
    if voice_lang == "none" and want_beat_sync and music_rec is not None:
        beat_times = (music_rec.get("meta") or {}).get("beat_times_s") or []
        if beat_times:
            planned_shots = snap_shots_to_beats(
                planned_shots,
                _load_shot_bounds(paths, planned_shots),
                beat_times,
            )

    keep_audio = bool(settings.render.keep_original_audio or audio_mode == "asmr_original")
    seg_files, sub_events, cut_duration_s = cut_shot_segments(
        paths, planned_shots, work_dir, keep_audio=keep_audio
    )
    cut_mp4 = concat_segments(seg_files, work_dir)

    engine_mode = str(video_row.get("engine") or "ffmpeg")
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
        if voice_sub_events:
            sub_events = voice_sub_events
    write_subtitle_file(sub_events, settings, work_dir, layout_preset=hook_layout)

    # Step 4: Burn ASS subtitles, mix music/silent track, and normalize to Master MP4 + cover.jpg
    rel_out = f"output/video_{video_id}.mp4"
    rel_cover = f"output/cover_{video_id}.jpg"
    abs_out = paths.media_dir / rel_out
    actual_duration_s = normalize_to_master(
        cut_mp4,
        abs_out,
        music_path=music_rec["path"] if music_rec is not None else None,
        voice_path=voice_track.audio_path if voice_track is not None else None,
        ass_filename=SUBTITLE_FILENAME if sub_events else None,
        cwd=work_dir,
        preset=preset,
        crf=18,
        mix_source_audio=keep_audio,
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
        try:
            rel_out, actual_duration_s = _render_to_master(
                paths, video_row, work_dir, preset=preset, music_asset_id=music_asset_id, mpt_client=mpt_client
            )
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

        should_score = (
            auto_score
            or score_provider is not None
            or score_override is not None
            or int(video_row.get("auto_render") or 0) == 1
        )
        waiting_id = score_or_send_to_approval(
            paths, video_id, should_score=should_score, score_provider=score_provider, score_override=score_override
        )
        if waiting_id is not None:  # this video, or a better-scored earlier attempt of it
            try:
                notify_pending(paths, waiting_id)
            except Exception as tg_exc:
                logger.warning("notify_pending hook warning for video #%d: %s", waiting_id, tg_exc)
        return f"Rendered video #{video_id} ({actual_duration_s:.2f}s) -> {rel_out}"

    except Exception as exc:
        err_msg = str(exc)[:500]
        with get_conn(paths.db_file) as conn:
            conn.execute(
                "UPDATE videos SET status = 'failed', error = ? WHERE id = ?",
                (err_msg, video_id),
            )
        raise

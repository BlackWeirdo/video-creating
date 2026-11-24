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
from videocreator.pipeline.export import (
    extract_cover_frame,
    normalize_to_master,
    resolve_canvas_dimensions,
)
from videocreator.pipeline.ffmpeg import RenderError
from videocreator.pipeline.preflight import check_all_platforms
from videocreator.pipeline.qc import run_video_qc
from videocreator.pipeline.render_inputs import pick_music_asset_record, pick_sfx_asset_path
from videocreator.pipeline.render_status import claim_for_render, score_or_send_to_approval
from videocreator.pipeline.render_steps import (
    SUBTITLE_FILENAME,
    add_internal_voice_over,
    add_voice_over,
    concat_segments,
    cut_shot_segments,
    write_subtitle_file,
)
from videocreator.pipeline.styles import resolve_style_preset
from videocreator.pipeline.subtitles import SubtitleEvent
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


def _shot_cut_timestamps(planned_shots: list[dict[str, Any]]) -> list[float]:
    cuts: list[float] = []
    cursor_s = 0.0
    for idx, ps in enumerate(planned_shots):
        dur = max(0.5, float(ps.get("duration_s") or 2.0))
        cursor_s += dur
        if idx < len(planned_shots) - 1:
            cuts.append(round(cursor_s, 3))
    return cuts


def finalize_master_export(
    paths: AppPaths,
    *,
    video_id: int,
    cut_mp4: Path,
    work_dir: Path,
    sub_events: list[SubtitleEvent],
    style_row: dict[str, Any] | None,
    hook_layout: str = "clean_bottom",
    aspect_ratio: str = "9:16",
    music_path: Path | None = None,
    voice_path: Path | None = None,
    cut_times_s: list[float] | None = None,
    mix_source_audio: bool = False,
    preset: str = "veryfast",
) -> tuple[str, str, float, dict[str, Any], dict[str, Any]]:
    """Burns styled subtitles, mixes voice + ducked music + SFX + loudnorm, extracts cover, and runs preflight & QC."""
    settings = load_settings(paths.config_file)
    width, height = resolve_canvas_dimensions(aspect_ratio)
    from videocreator.pipeline.probe import probe_duration

    total_dur = probe_duration(cut_mp4)
    write_subtitle_file(
        sub_events,
        settings,
        work_dir,
        layout_preset=hook_layout,
        style_preset_row=style_row,
        play_res_x=width,
        play_res_y=height,
        total_duration_s=total_dur,
    )

    sfx_events: list[tuple[Path, float]] = []
    if style_row and style_row.get("sfx_transition_asset_id") and cut_times_s:
        sfx_path = pick_sfx_asset_path(paths, int(style_row["sfx_transition_asset_id"]))
        if sfx_path is not None:
            sfx_events = [(sfx_path, t) for t in cut_times_s[:6]]

    rel_out = f"output/video_{video_id}.mp4"
    rel_cover = f"output/cover_{video_id}.jpg"
    abs_out = paths.media_dir / rel_out

    actual_duration_s = normalize_to_master(
        cut_mp4,
        abs_out,
        music_path=music_path,
        voice_path=voice_path,
        ass_filename=SUBTITLE_FILENAME if sub_events else None,
        cwd=work_dir,
        preset=preset,
        crf=18,
        mix_source_audio=mix_source_audio,
        width=width,
        height=height,
        ducking=bool(style_row.get("ducking_enabled", True)) if style_row else True,
        music_volume=float(style_row.get("music_volume", 0.22)) if style_row else 0.2,
        sfx_events=sfx_events,
    )
    extract_cover_frame(abs_out, paths.media_dir / rel_cover, at_s=1.0)
    preflight_map = check_all_platforms(abs_out, settings)
    qc_report = run_video_qc(abs_out, expect_voice=(voice_path is not None))
    return rel_out, rel_cover, actual_duration_s, preflight_map, qc_report


def _resolve_video_style_row(paths: AppPaths, video_row: dict[str, Any]) -> dict[str, Any]:
    explicit = str(video_row.get("style_preset") or "").strip()
    if explicit:
        return resolve_style_preset(paths.db_file, explicit)
    ws_id = int(video_row.get("workspace_id") or 1)
    ws_row = query_one(paths.db_file, "SELECT style_preset FROM workspaces WHERE id = ?", (ws_id,))
    ws_style = str(ws_row["style_preset"]) if ws_row and ws_row.get("style_preset") else "tiktok_karaoke"
    return resolve_style_preset(paths.db_file, ws_style)


def _save_render_cache(
    paths: AppPaths,
    *,
    video_id: int,
    cut_mp4: Path,
    voice_path: Path | None,
    sub_events: list[SubtitleEvent],
    cut_times_s: list[float],
    music_asset_id: int | None,
    aspect_ratio: str,
    mix_source_audio: bool,
) -> dict[str, Any]:
    from videocreator.pipeline.render_steps import subtitle_events_to_json

    cache_dir = paths.media_dir / "render_cache" / f"video_{video_id}"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached_cut = cache_dir / "cut.mp4"
    shutil.copy2(cut_mp4, cached_cut)
    rel_cut = f"render_cache/video_{video_id}/cut.mp4"

    rel_voice = ""
    if voice_path is not None and voice_path.exists():
        cached_voice = cache_dir / "voice.wav"
        shutil.copy2(voice_path, cached_voice)
        rel_voice = f"render_cache/video_{video_id}/voice.wav"

    subs_file = cache_dir / "sub_events.json"
    subs_file.write_text(
        json.dumps(subtitle_events_to_json(sub_events), ensure_ascii=False),
        encoding="utf-8",
    )
    return {
        "cut_mp4": rel_cut,
        "voice_wav": rel_voice,
        "sub_events_file": f"render_cache/video_{video_id}/sub_events.json",
        "cut_times_s": cut_times_s,
        "music_asset_id": music_asset_id,
        "aspect_ratio": aspect_ratio,
        "mix_source_audio": bool(mix_source_audio),
    }


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

    aspect_ratio = str(
        video_row.get("aspect_ratio") or plan.get("aspect_ratio") or "9:16"
    ).strip() or "9:16"
    width, height = resolve_canvas_dimensions(aspect_ratio)
    style_row = _resolve_video_style_row(paths, video_row)

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
    row_vlang = str(video_row.get("voice_lang") or "none")
    plan_vlang = str(plan.get("voice_lang") or "")
    voice_lang = row_vlang if row_vlang in ("vi", "en") else (plan_vlang or row_vlang or "none")

    want_beat_sync = bool(blueprint) or bool(plan.get("beat_sync"))
    if row_vlang == "none" and want_beat_sync and music_rec is not None:
        beat_times = (music_rec.get("meta") or {}).get("beat_times_s") or []
        if beat_times:
            planned_shots = snap_shots_to_beats(
                planned_shots,
                _load_shot_bounds(paths, planned_shots),
                beat_times,
            )

    keep_audio = bool(settings.render.keep_original_audio or audio_mode == "asmr_original")
    seg_files, sub_events, cut_duration_s = cut_shot_segments(
        paths,
        planned_shots,
        work_dir,
        keep_audio=keep_audio,
        target_width=width,
        target_height=height,
    )
    cut_mp4 = concat_segments(seg_files, work_dir)
    cut_times_s = _shot_cut_timestamps(planned_shots)

    engine_mode = str(video_row.get("engine") or "ffmpeg")
    voice_track = None
    tts_notes: list[str] = []
    if engine_mode == "mpt" and voice_lang in ("vi", "en"):
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
    elif row_vlang in ("vi", "en"):
        voice_track, voice_sub_events, tts_notes = add_internal_voice_over(
            paths,
            video_id,
            planned_shots=planned_shots,
            voice_lang=row_vlang,
            work_dir=work_dir,
            video_duration_s=cut_duration_s,
        )
        if voice_sub_events:
            sub_events = voice_sub_events

    voice_file = voice_track.audio_path if voice_track is not None else None
    music_file = music_rec["path"] if music_rec is not None else None
    use_style_row = None if (hook_layout in ("big_center_title", "top_banner", "kinetic_words") and not str(video_row.get("style_preset") or "").strip()) else style_row

    rel_out, rel_cover, actual_duration_s, preflight_map, qc_report = finalize_master_export(
        paths,
        video_id=video_id,
        cut_mp4=cut_mp4,
        work_dir=work_dir,
        sub_events=sub_events,
        style_row=use_style_row,
        hook_layout=hook_layout,
        aspect_ratio=aspect_ratio,
        music_path=music_file,
        voice_path=voice_file,
        cut_times_s=cut_times_s,
        mix_source_audio=keep_audio,
        preset=preset,
    )

    render_cache = _save_render_cache(
        paths,
        video_id=video_id,
        cut_mp4=cut_mp4,
        voice_path=voice_file,
        sub_events=sub_events,
        cut_times_s=cut_times_s,
        music_asset_id=music_rec["id"] if music_rec is not None else None,
        aspect_ratio=aspect_ratio,
        mix_source_audio=keep_audio,
    )

    transition(paths.db_file, video_id, "rendered", expected_from="rendering")
    fresh_notes_row = query_one(
        paths.db_file, "SELECT quality_notes FROM videos WHERE id = ?", (video_id,)
    )
    with get_conn(paths.db_file) as conn:
        existing_notes = str(
            (fresh_notes_row or {}).get("quality_notes") or video_row.get("quality_notes") or ""
        ).strip()
        combined_notes = "\n".join(n for n in [existing_notes, *tts_notes] if n).strip()
        conn.execute(
            """
            UPDATE videos
            SET output_path = ?,
                cover_path = ?,
                duration_s = ?,
                preflight_json = ?,
                qc_json = ?,
                render_cache_json = ?,
                aspect_ratio = ?,
                style_preset = ?,
                quality_notes = ?,
                error = NULL
            WHERE id = ?
            """,
            (
                rel_out,
                rel_cover,
                round(actual_duration_s, 3),
                json.dumps(preflight_map, ensure_ascii=False),
                json.dumps(qc_report, ensure_ascii=False),
                json.dumps(render_cache, ensure_ascii=False),
                aspect_ratio,
                style_row["id"],
                combined_notes or None,
                video_id,
            ),
        )
        record_audit(
            conn,
            actor="worker",
            action="video.rendered",
            object_type="video",
            object_id=video_id,
            detail=f"duration={actual_duration_s:.2f}s, style={style_row['id']}, ratio={aspect_ratio}, out={rel_out}",
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
            from videocreator.approvals import try_autopilot_approve

            scheduled_by_autopilot = False
            try:
                scheduled_by_autopilot = try_autopilot_approve(paths, waiting_id)
            except Exception as ap_exc:
                logger.warning("Autopilot approval skipped for video #%d: %s", waiting_id, ap_exc)
            if not scheduled_by_autopilot:
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

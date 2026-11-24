"""Localize render stage: segment assembly, multi-speaker TTS, BGM ducking & QC."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from videocreator.approvals import try_autopilot_approve
from videocreator.db import get_conn, query_one, record_audit
from videocreator.job_store import report_active_job_progress
from videocreator.jsonutil import loads_or
from videocreator.paths import AppPaths
from videocreator.pipeline.assembly import save_render_cache
from videocreator.pipeline.export import resolve_canvas_dimensions
from videocreator.pipeline.ffmpeg import RenderError
from videocreator.pipeline.localize.extract import run_localize_extract
from videocreator.pipeline.localize.project import (
    get_localize_project,
    normalize_hardsub_mode,
    resolve_source_media,
    set_project_status,
    validate_localize_policy,
)
from videocreator.pipeline.localize.segments import (
    boxes_for_segment_window,
    cut_localized_segment,
    cut_real_product_shot_segment,
)
from videocreator.pipeline.localize.voice import resolve_segment_voice_spec
from videocreator.pipeline.probe import probe_video
from videocreator.pipeline.render import finalize_master_export
from videocreator.pipeline.render_status import claim_for_render, score_or_send_to_approval
from videocreator.pipeline.render_steps import concat_segments
from videocreator.pipeline.styles import resolve_style_preset
from videocreator.pipeline.subtitles import SubtitleEvent
from videocreator.state import transition
from videocreator.tts.synthesizer import (
    TTSUnavailableError,
    synthesize_speech_segments,
    synthesize_timed_speaker_segments,
)


def run_localize_render(
    paths: AppPaths,
    project_id: int,
    *,
    tts_provider: str = "auto",
    target_accounts: list[int] | None = None,
    auto_approve: bool = True,
) -> dict[str, Any]:
    """Render localized/remixed video using dynamic OCR/LaMa hardsub removal, multi-speaker TTS & QC."""
    proj = get_localize_project(paths.db_file, project_id)
    if proj is None:
        raise ValueError(f"Localize project #{project_id} not found")

    ws_id = int(proj["workspace_id"])
    mode = str(proj["mode"])
    validate_localize_policy(
        paths.db_file,
        ws_id,
        mode,
        clone_source_voice=bool(proj.get("clone_source_voice")),
        clone_consent_confirmed=bool(proj.get("clone_consent_confirmed")),
    )

    segments: list[dict[str, Any]] = list(proj.get("segments") or [])
    if not segments:
        proj = run_localize_extract(paths, project_id)
        segments = list(proj.get("segments") or [])
    if not segments:
        raise RenderError(f"Localize project #{project_id} produced 0 segments")

    product_ids = [int(p) for p in (proj.get("product_ids") or []) if int(p) > 0]
    if mode == "hybrid_remix" and product_ids:
        if not any(int(s.get("replace_shot_id") or 0) > 0 for s in segments):
            raise ValueError(
                "Hybrid Remix với sản phẩm yêu cầu ít nhất 1 phân đoạn gắn `replace_shot_id` thật từ kho shots."
            )

    set_project_status(paths.db_file, project_id, "rendering", error=None)
    work_dir = paths.work_dir / f"localize_{project_id}"
    if work_dir.exists():
        shutil.rmtree(work_dir, ignore_errors=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    try:
        src_mp4 = resolve_source_media(paths, proj)
        src_info = probe_video(src_mp4)
        src_w, src_h = max(64, src_info.width), max(64, src_info.height)
        src_dur = max(0.5, src_info.duration_s)

        aspect_ratio = str(proj.get("aspect_ratio") or "9:16")
        canvas_w, canvas_h = resolve_canvas_dimensions(aspect_ratio)
        style_row = resolve_style_preset(
            paths.db_file, str(proj.get("style_preset") or "tiktok_karaoke")
        )
        hardsub_mode = normalize_hardsub_mode(str(proj.get("hardsub_mode") or "blur_bar"))
        ocr_cues = list(proj.get("ocr_cues") or [])
        fallback_box = dict(
            proj.get("hardsub_box") or {"x": 0.06, "y": 0.74, "w": 0.88, "h": 0.16}
        )

        seg_files: list[str] = []
        raw_sub_specs: list[dict[str, Any]] = []
        timed_tts_items: list[dict[str, Any]] = []
        cursor_s = 0.0
        used_shot_ids: list[int] = []
        any_lama_used = False
        any_inpaint_needed = False
        any_cloned_used = False
        total_segs = max(1, len(segments))

        for idx, seg in enumerate(segments, start=1):
            report_active_job_progress(
                0.10 + 0.40 * ((idx - 1) / total_segs),
                f"Đang xử lý khung hình & xóa chữ cứng đoạn {idx}/{total_segs}...",
            )
            st = max(0.0, float(seg.get("start_s") or 0.0))
            en = max(st + 0.5, float(seg.get("end_s") or (st + 1.5)))
            dur_s = round(en - st, 3)
            seg_name = f"loc_seg_{idx:02d}.mp4"
            seg_path = work_dir / seg_name

            rep_shot = int(seg.get("replace_shot_id") or 0)
            if mode == "hybrid_remix" and rep_shot > 0:
                cut_real_product_shot_segment(
                    paths,
                    rep_shot,
                    seg_path,
                    duration_s=dur_s,
                    canvas_w=canvas_w,
                    canvas_h=canvas_h,
                    work_dir=work_dir,
                )
                used_shot_ids.append(rep_shot)
            else:
                active_boxes, has_sub = boxes_for_segment_window(seg, ocr_cues, fallback_box)
                if hardsub_mode == "ocr_inpaint" and has_sub:
                    any_inpaint_needed = True
                used_lama = cut_localized_segment(
                    paths,
                    src_mp4,
                    seg_path,
                    start_s=st,
                    duration_s=dur_s,
                    src_duration_s=src_dur,
                    src_w=src_w,
                    src_h=src_h,
                    canvas_w=canvas_w,
                    canvas_h=canvas_h,
                    hardsub_mode=hardsub_mode,
                    active_boxes=active_boxes if has_sub else [],
                    fallback_box=fallback_box,
                    anti_dup=dict(proj.get("anti_dup") or {}),
                    mode=mode,
                    work_dir=work_dir,
                )
                if used_lama:
                    any_lama_used = True

            seg_files.append(seg_name)
            main_txt = (
                str(seg.get("translated_text") or seg.get("source_text") or "").strip() or "Video"
            )
            sec_txt = str(seg.get("source_text") or "").strip()
            prov, v_id, ref_audio = resolve_segment_voice_spec(
                paths, proj, seg, requested_provider=tts_provider
            )
            if ref_audio is not None:
                any_cloned_used = True

            raw_sub_specs.append(
                {
                    "start_s": round(cursor_s, 3),
                    "end_s": round(cursor_s + dur_s, 3),
                    "text": main_txt,
                    "secondary_text": sec_txt if sec_txt != main_txt else "",
                }
            )
            timed_tts_items.append(
                {
                    "text": main_txt,
                    "offset_s": round(cursor_s, 3),
                    "duration_s": dur_s,
                    "provider": prov,
                    "voice": v_id,
                    "ref_audio": ref_audio,
                }
            )
            cursor_s += dur_s

        cut_mp4 = concat_segments(seg_files, work_dir)
        cut_times_s = [float(sp["end_s"]) for sp in raw_sub_specs[:-1]]

        sim_flags: list[str] = [
            f
            for f in (proj.get("simulation_flags") or [])
            if f not in ("ocr_inpaint_delogo_fallback", "tts_tone_placeholder")
        ]
        if hardsub_mode == "ocr_inpaint" and any_inpaint_needed and not any_lama_used:
            sim_flags.append("ocr_inpaint_delogo_fallback")

        target_lang = str(proj.get("target_lang") or "vi")
        legacy_lang = "vi" if target_lang.strip().lower().startswith("vi") else "en"
        preview_dir = paths.media_dir / "localize" / f"proj_{project_id}" / "previews"

        report_active_job_progress(
            0.55, f"Đang tổng hợp giọng lồng tiếng cho {total_segs} phân đoạn..."
        )
        try:
            voice_track, preview_paths, _warnings = synthesize_timed_speaker_segments(
                paths,
                timed_tts_items,
                work_dir=work_dir / "tts",
                preview_out_dir=preview_dir,
            )
            if (
                any(t in voice_track.provider for t in ("test_tone", "local"))
                and "tts_tone_placeholder" not in sim_flags
            ):
                sim_flags.append("tts_tone_placeholder")
        except TTSUnavailableError:
            fallback_lines = [(str(it["text"]), float(it["duration_s"])) for it in timed_tts_items]
            voice_track, _warnings = synthesize_speech_segments(
                fallback_lines,
                lang=legacy_lang,
                voice=str(proj.get("voice_id") or "vi-VN-HoaiMyNeural"),
                provider_name="test_tone",
                work_dir=work_dir / "tts_fallback",
            )
            preview_paths = []
            if "tts_tone_placeholder" not in sim_flags:
                sim_flags.append("tts_tone_placeholder")

        sub_events: list[SubtitleEvent] = []
        for idx, sp in enumerate(raw_sub_specs):
            ev_st = float(sp["start_s"])
            ev_en = float(sp["end_s"])
            seg_words = tuple(
                (wt.word, wt.start_s, wt.end_s)
                for wt in voice_track.word_timings
                if wt.start_s >= ev_st - 0.05 and wt.end_s <= ev_en + 0.15
            )
            sub_events.append(
                SubtitleEvent(
                    start_s=ev_st,
                    end_s=ev_en,
                    text=str(sp["text"]),
                    secondary_text=str(sp["secondary_text"]),
                    words=seg_words,
                )
            )
            if idx < len(segments) and idx < len(preview_paths) and preview_paths[idx]:
                try:
                    rel_prev = str(
                        Path(preview_paths[idx]).relative_to(paths.media_dir)
                    ).replace("\\", "/")
                    segments[idx]["preview_audio_url"] = f"/files/{rel_prev}"
                except ValueError:
                    pass

        bgm_path = (
            paths.media_dir / str(proj["bgm_track_path"])
            if proj.get("bgm_track_path")
            else None
        )
        if bgm_path is not None and not bgm_path.exists():
            bgm_path = None

        plan_shots = [
            {
                "shot_id": int(seg.get("replace_shot_id") or 0),
                "duration_s": round(max(0.5, float(seg["end_s"]) - float(seg["start_s"])), 3),
                "text": str(seg.get("translated_text") or ""),
            }
            for seg in segments
        ]
        if proj.get("source_video_id") and not used_shot_ids:
            src_v = query_one(
                paths.db_file,
                "SELECT plan_json, product_ids_json FROM videos WHERE id = ?",
                (int(proj["source_video_id"]),),
            )
            if src_v:
                src_plan = loads_or(src_v.get("plan_json"), {})
                if isinstance(src_plan, dict) and src_plan.get("shots"):
                    plan_shots = list(src_plan["shots"])

        plan_payload = {
            "localize_project_id": project_id,
            "mode": mode,
            "hardsub_mode": hardsub_mode,
            "voice_provider": voice_track.provider,
            "cloned_source_voice": any_cloned_used,
            "shots": plan_shots,
        }
        acct_ids = [int(a) for a in (target_accounts or []) if int(a) > 0]
        with get_conn(paths.db_file) as conn:
            cur = conn.execute(
                """
                INSERT INTO videos (
                    workspace_id, product_ids_json, engine, status, plan_json,
                    voice_lang, caption_lang, target_lang, target_accounts_json,
                    style_preset, aspect_ratio
                )
                VALUES (?, ?, 'ffmpeg', 'planned', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ws_id,
                    json.dumps(product_ids),
                    json.dumps(plan_payload, ensure_ascii=False),
                    legacy_lang,
                    legacy_lang,
                    target_lang,
                    json.dumps(acct_ids),
                    style_row["id"],
                    aspect_ratio,
                ),
            )
            video_id = int(cur.lastrowid)

        claim_for_render(paths, video_id, "planned")
        report_active_job_progress(
            0.80, "Đang trộn nhạc nền ducking, phụ đề ASS, chuẩn hóa -14 LUFS & QC..."
        )
        rel_out, rel_cover, actual_dur, preflight_map, qc_report = finalize_master_export(
            paths,
            video_id=video_id,
            cut_mp4=cut_mp4,
            work_dir=work_dir,
            sub_events=sub_events,
            style_row=style_row,
            aspect_ratio=aspect_ratio,
            music_path=bgm_path,
            voice_path=voice_track.audio_path,
            cut_times_s=cut_times_s,
            mix_source_audio=False,
        )
        render_cache = save_render_cache(
            paths,
            video_id=video_id,
            cut_mp4=cut_mp4,
            voice_path=voice_track.audio_path,
            sub_events=sub_events,
            cut_times_s=cut_times_s,
            music_asset_id=None,
            aspect_ratio=aspect_ratio,
            mix_source_audio=False,
        )
        transition(paths.db_file, video_id, "rendered", expected_from="rendering")
        q_score = 8.8 if qc_report.get("passed") else 5.5
        with get_conn(paths.db_file) as conn:
            conn.execute(
                """
                UPDATE videos
                SET output_path = ?,
                    cover_path = ?,
                    duration_s = ?,
                    preflight_json = ?,
                    qc_json = ?,
                    render_cache_json = ?,
                    quality_score = ?,
                    error = NULL
                WHERE id = ?
                """,
                (
                    rel_out,
                    rel_cover,
                    round(actual_dur, 3),
                    json.dumps(preflight_map, ensure_ascii=False),
                    json.dumps(qc_report, ensure_ascii=False),
                    json.dumps(render_cache, ensure_ascii=False),
                    q_score,
                    video_id,
                ),
            )
        score_or_send_to_approval(
            paths, video_id, should_score=False, score_provider=None, score_override=None
        )
        if auto_approve:
            try_autopilot_approve(paths, video_id)

        with get_conn(paths.db_file) as conn:
            conn.execute(
                """
                UPDATE localize_projects
                SET output_video_id = ?,
                    segments_json = ?,
                    simulation_flags_json = ?,
                    status = 'completed',
                    error = NULL,
                    updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
                WHERE id = ?
                """,
                (
                    video_id,
                    json.dumps(segments, ensure_ascii=False),
                    json.dumps(sim_flags, ensure_ascii=False),
                    int(project_id),
                ),
            )
            record_audit(
                conn,
                actor="localize",
                action="render_localize",
                object_type="localize_project",
                object_id=int(project_id),
                detail=f"video #{video_id} ({rel_out}) voice={voice_track.provider} cloned={any_cloned_used}",
            )
            if any_cloned_used:
                record_audit(
                    conn,
                    actor="localize",
                    action="render_source_voice_clone",
                    object_type="localize_project",
                    object_id=int(project_id),
                    detail=f"video #{video_id} project-scoped speaker cloning executed",
                )

        report_active_job_progress(0.96, f"Hoàn tất xuất video Việt hóa #{video_id}")
        done_proj = get_localize_project(paths.db_file, project_id)
        assert done_proj is not None
        return done_proj
    except Exception as exc:
        set_project_status(paths.db_file, project_id, "failed", error=str(exc))
        raise
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def run_localize_render_job(paths: AppPaths, project_id: int) -> str:
    proj = run_localize_render(paths, project_id)
    return str(proj.get("status") or "completed")

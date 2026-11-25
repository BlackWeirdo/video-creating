"""Localize extraction stage: MDX-Net stem separation, RapidOCR + Faster-Whisper, CPU diarization & translation."""
from __future__ import annotations

import json
from typing import Any

from videocreator.db import get_conn, query_one
from videocreator.job_store import report_active_job_progress
from videocreator.jsonutil import loads_or
from videocreator.models_manager import transcribe_media_segments
from videocreator.paths import AppPaths
from videocreator.pipeline.audio_sep import separate_vocals_and_bgm_smart
from videocreator.pipeline.diarization import diarize_segments_on_cpu
from videocreator.pipeline.localize.project import (
    get_localize_project,
    pick_workspace_product_shots,
    resolve_source_media,
    set_project_status,
    validate_localize_policy,
)
from videocreator.pipeline.localize.translate import translate_localize_segments
from videocreator.pipeline.ocr_hardsub import (
    align_ocr_and_whisper_segments,
    extract_hardsub_ocr_cues,
)


def run_localize_extract(
    paths: AppPaths,
    project_id: int,
    *,
    provider_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run MDX-Net stem separation, RapidOCR + Faster-Whisper alignment, CPU diarization & AI/NLLB translation."""
    proj = get_localize_project(paths.db_file, project_id)
    if proj is None:
        raise ValueError(f"Localize project #{project_id} not found")

    validate_localize_policy(
        paths.db_file,
        int(proj["workspace_id"]),
        str(proj["mode"]),
        clone_source_voice=bool(proj.get("clone_source_voice")),
        clone_consent_confirmed=bool(proj.get("clone_consent_confirmed")),
    )
    set_project_status(paths.db_file, project_id, "extracting", error=None)

    try:
        report_active_job_progress(0.10, "Đang tách lời thoại & nhạc nền (MDX-Net CPU)...")
        src_mp4 = resolve_source_media(paths, proj)
        proj_dir = paths.media_dir / "localize" / f"proj_{project_id}"
        vocal_wav, bgm_wav, used_mdx = separate_vocals_and_bgm_smart(paths, src_mp4, proj_dir)
        rel_vocal = str(vocal_wav.relative_to(paths.media_dir)).replace("\\", "/")
        rel_bgm = str(bgm_wav.relative_to(paths.media_dir)).replace("\\", "/")

        sim_flags: list[str] = []
        if not used_mdx:
            sim_flags.append("audio_sep_midside_fallback")

        ocr_cues: list[dict[str, Any]] = []
        raw_segments: list[dict[str, Any]] = []

        if proj.get("source_video_id"):
            v_row = query_one(
                paths.db_file,
                "SELECT plan_json FROM videos WHERE id = ?",
                (int(proj["source_video_id"]),),
            )
            plan = loads_or((v_row or {}).get("plan_json"), {})
            cursor = 0.0
            for ps in plan.get("shots") or []:
                dur = max(0.6, float(ps.get("duration_s") or 1.5))
                txt = str(ps.get("text") or "").strip() or f"Shot {len(raw_segments) + 1}"
                raw_segments.append(
                    {
                        "index": len(raw_segments),
                        "start_s": round(cursor, 3),
                        "end_s": round(cursor + dur, 3),
                        "source_text": txt,
                    }
                )
                cursor += dur

        if not raw_segments:
            if str(proj.get("hardsub_mode") or "blur_bar") != "none":
                report_active_job_progress(0.32, "Đang quét OCR phụ đề cứng trên khung hình...")
                ocr_cues = extract_hardsub_ocr_cues(src_mp4, sample_every_s=0.5)

            report_active_job_progress(0.50, "Đang chép lời Faster-Whisper & căn mốc thời gian...")
            has_sidecar = any(src_mp4.with_suffix(ext).exists() for ext in (".srt", ".vtt"))
            asr_input = src_mp4 if has_sidecar or not vocal_wav.is_file() else vocal_wav
            whisper_segs = transcribe_media_segments(
                paths,
                asr_input,
                lang=str(proj.get("source_lang") or "auto"),
                whisper_size=str(proj.get("whisper_size") or "small"),
            )
            raw_segments, origin_kind = align_ocr_and_whisper_segments(whisper_segs, ocr_cues)
            if origin_kind == "fallback" and any(
                str(s.get("source_text") or "").startswith("Segment ") for s in raw_segments
            ):
                sim_flags.append("asr_silencedetect_placeholder")

        report_active_job_progress(0.68, "Đang phân biệt người nói (3D-Speaker ONNX CPU)...")
        diarized_segments, speaker_cfg, used_diar = diarize_segments_on_cpu(
            paths,
            vocal_wav,
            raw_segments,
            speakers_dir=proj_dir / "speakers",
            media_root=paths.media_dir,
        )
        if not used_diar and not proj.get("source_video_id"):
            sim_flags.append("diarization_single_speaker_fallback")

        default_voice = str(proj.get("voice_id") or "vi-VN-HoaiMyNeural").strip()
        if len(speaker_cfg) == 1 and "SPK_1" in speaker_cfg and default_voice:
            speaker_cfg["SPK_1"]["voice_id"] = default_voice

        report_active_job_progress(0.84, "Đang dịch kịch bản theo ngân sách âm tiết...")
        translated_segments, trans_engine = translate_localize_segments(
            paths,
            diarized_segments,
            source_lang=str(proj.get("source_lang") or "auto"),
            target_lang=str(proj.get("target_lang") or "vi"),
            translation_style=str(proj.get("translation_style") or "natural_tiktok"),
            provider_overrides=provider_overrides,
        )
        if trans_engine == "nllb_offline":
            sim_flags.append("offline_nllb_translation")
        elif trans_engine == "pending":
            sim_flags.append("translation_pending")

        mode = str(proj["mode"])
        shots_pool = (
            pick_workspace_product_shots(
                paths.db_file,
                int(proj["workspace_id"]),
                [int(x) for x in proj.get("product_ids") or []],
            )
            if mode == "hybrid_remix"
            else []
        )

        segments: list[dict[str, Any]] = []
        for idx, seg in enumerate(translated_segments):
            replace_shot_id = int(seg.get("replace_shot_id") or 0)
            if (
                mode == "hybrid_remix"
                and shots_pool
                and idx == len(translated_segments) - 1
                and replace_shot_id == 0
            ):
                replace_shot_id = shots_pool[idx % len(shots_pool)]
            segments.append({**seg, "index": idx, "replace_shot_id": replace_shot_id})

        next_box = dict(proj.get("hardsub_box") or {"x": 0.06, "y": 0.74, "w": 0.88, "h": 0.16})
        if ocr_cues:
            x1 = min(float(c["box"]["x"]) for c in ocr_cues)
            y1 = min(float(c["box"]["y"]) for c in ocr_cues)
            x2 = max(float(c["box"]["x"]) + float(c["box"]["w"]) for c in ocr_cues)
            y2 = max(float(c["box"]["y"]) + float(c["box"]["h"]) for c in ocr_cues)
            next_box = {
                "x": round(max(0.0, x1), 4),
                "y": round(max(0.0, y1), 4),
                "w": round(min(1.0 - max(0.0, x1), x2 - x1), 4),
                "h": round(min(1.0 - max(0.0, y1), y2 - y1), 4),
            }

        with get_conn(paths.db_file) as conn:
            conn.execute(
                """
                UPDATE localize_projects
                SET vocal_track_path = ?,
                    bgm_track_path = ?,
                    segments_json = ?,
                    speaker_config_json = ?,
                    ocr_cues_json = ?,
                    hardsub_box_json = ?,
                    simulation_flags_json = ?,
                    status = 'ready_to_edit',
                    error = NULL,
                    updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
                WHERE id = ?
                """,
                (
                    rel_vocal,
                    rel_bgm,
                    json.dumps(segments, ensure_ascii=False),
                    json.dumps(
                        {"speakers": speaker_cfg, "trans_engine": trans_engine},
                        ensure_ascii=False,
                    ),
                    json.dumps(ocr_cues, ensure_ascii=False),
                    json.dumps(next_box, ensure_ascii=False),
                    json.dumps(sim_flags, ensure_ascii=False),
                    int(project_id),
                ),
            )
        report_active_job_progress(0.96, "Hoàn tất tách lời & dịch kịch bản")
        updated = get_localize_project(paths.db_file, project_id)
        assert updated is not None
        return updated
    except Exception as exc:
        set_project_status(paths.db_file, project_id, "failed", error=str(exc))
        raise


def run_localize_extract_job(paths: AppPaths, project_id: int) -> str:
    from videocreator.pipeline.compute_job import run_studio_project_job

    return run_studio_project_job(
        run_localize_extract, paths, project_id, default_status="ready_to_edit"
    )

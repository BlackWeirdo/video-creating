"""Localize, Reup, Hybrid Remix & Internationalize Studio pipeline with real CPU AI (Stage R3)."""
from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any

from videocreator.approvals import try_autopilot_approve
from videocreator.db import get_conn, query_all, query_one, record_audit
from videocreator.jsonutil import loads_or
from videocreator.models_manager import get_local_model, transcribe_media_segments
from videocreator.paths import AppPaths
from videocreator.pipeline.audio_sep import separate_vocals_and_bgm_smart
from videocreator.pipeline.diarization import diarize_segments_on_cpu
from videocreator.pipeline.export import resolve_canvas_dimensions
from videocreator.pipeline.ffmpeg import RenderError, run_ffmpeg
from videocreator.pipeline.ocr_hardsub import (
    align_ocr_and_whisper_segments,
    extract_hardsub_ocr_cues,
    inpaint_segment_with_lama,
)
from videocreator.pipeline.probe import probe_duration, probe_video
from videocreator.pipeline.render import _save_render_cache, finalize_master_export
from videocreator.pipeline.render_inputs import build_segment_filter_args
from videocreator.pipeline.render_status import claim_for_render, score_or_send_to_approval
from videocreator.pipeline.render_steps import _load_shot_source, concat_segments
from videocreator.pipeline.styles import resolve_style_preset
from videocreator.pipeline.subtitles import SubtitleEvent
from videocreator.pipeline.translate_vi import translate_localize_segments
from videocreator.state import transition
from videocreator.trends.download import fetch_reference_video
from videocreator.tts.syllables import count_syllables, max_syllables_for_duration
from videocreator.tts.synthesizer import (
    TTSUnavailableError,
    synthesize_speech_segments,
    synthesize_timed_speaker_segments,
)
from videocreator.workspaces import require_workspace

logger = logging.getLogger("videocreator.pipeline.localize")

VALID_LOCALIZE_MODES: frozenset[str] = frozenset({"reup_vi", "hybrid_remix", "intl_export"})
VALID_HARDSUB_MODES: frozenset[str] = frozenset(
    {"none", "blur_bar", "crop_frame", "ocr_inpaint", "lama_inpaint"}
)
VALID_WHISPER_SIZES: frozenset[str] = frozenset({"small", "medium"})
VALID_TRANSLATION_STYLES: frozenset[str] = frozenset({"natural_tiktok", "literal"})


def _normalize_hardsub_mode(raw_mode: str) -> str:
    clean = (raw_mode or "blur_bar").strip().lower()
    if clean not in VALID_HARDSUB_MODES:
        raise ValueError(f"Unsupported hardsub_mode '{raw_mode}'")
    return "ocr_inpaint" if clean == "lama_inpaint" else clean


def validate_localize_policy(
    db_file: Path,
    workspace_id: int,
    mode: str,
    *,
    clone_source_voice: bool = False,
    clone_consent_confirmed: bool = False,
) -> dict[str, Any]:
    """Enforces workspace `content_policy` and Decision 7c voice-cloning safeguards."""
    clean_mode = (mode or "").strip()
    if clean_mode not in VALID_LOCALIZE_MODES:
        raise ValueError(f"Unsupported localize mode '{mode}'")

    ws = require_workspace(db_file, workspace_id)
    policy = str(ws.get("content_policy") or "strict_footage")
    if policy == "strict_footage" and clean_mode != "intl_export":
        raise PermissionError(
            "Workspace 'strict_footage' chỉ cho phép chế độ 'intl_export' từ video thật của thương hiệu; "
            "không cho phép 'reup_vi' hay 'hybrid_remix'."
        )
    if policy == "hybrid_remix" and clean_mode == "reup_vi":
        raise PermissionError(
            "Workspace 'hybrid_remix' không cho phép reup 100%; hãy chọn 'hybrid_remix' (tráo shot thật) hoặc 'intl_export'."
        )
    if clone_source_voice:
        if policy not in ("hybrid_remix", "full_ai"):
            raise PermissionError(
                "Nhân bản giọng người nói gốc bị cấm trong workspace 'strict_footage'; chỉ cho phép ở 'hybrid_remix' hoặc 'full_ai'."
            )
        if not clone_consent_confirmed:
            raise PermissionError(
                "Bật nhân bản giọng người nói gốc yêu cầu xác nhận trách nhiệm sử dụng (`clone_consent_confirmed=true`)."
            )
    return ws


def create_localize_project(
    paths: AppPaths,
    *,
    workspace_id: int,
    title: str,
    mode: str,
    source_url: str = "",
    source_media_path: str = "",
    source_trend_id: int | None = None,
    source_video_id: int | None = None,
    source_lang: str = "auto",
    target_lang: str = "vi",
    hardsub_mode: str = "blur_bar",
    hardsub_box: dict[str, float] | None = None,
    anti_dup: dict[str, Any] | None = None,
    product_ids: list[int] | None = None,
    style_preset: str = "tiktok_karaoke",
    aspect_ratio: str = "9:16",
    voice_id: str = "vi-VN-HoaiMyNeural",
    whisper_size: str = "small",
    translation_style: str = "natural_tiktok",
    clone_source_voice: bool = False,
    clone_consent_confirmed: bool = False,
    actor: str = "api",
) -> dict[str, Any]:
    ws = validate_localize_policy(
        paths.db_file,
        workspace_id,
        mode,
        clone_source_voice=clone_source_voice,
        clone_consent_confirmed=clone_consent_confirmed,
    )
    clean_hardsub = _normalize_hardsub_mode(hardsub_mode)
    clean_whisper = (whisper_size or "small").strip().lower()
    if clean_whisper not in VALID_WHISPER_SIZES:
        raise ValueError(f"Unsupported whisper_size '{whisper_size}'")
    clean_style = (translation_style or "natural_tiktok").strip().lower()
    if clean_style not in VALID_TRANSLATION_STYLES:
        raise ValueError(f"Unsupported translation_style '{translation_style}'")

    clean_title = (title or "").strip()
    if not clean_title:
        raise ValueError("Localize project title is required")

    if str(ws.get("content_policy") or "") == "strict_footage" and source_video_id is None and not source_media_path:
        raise PermissionError(
            "Workspace 'strict_footage' chỉ quốc tế hóa được video/footage có sẵn trong workspace."
        )

    box_json = json.dumps(
        hardsub_box or {"x": 0.06, "y": 0.74, "w": 0.88, "h": 0.16},
        ensure_ascii=False,
    )
    anti_json = json.dumps(
        anti_dup or {"mirror": False, "zoom": 1.04, "color_eq": True},
        ensure_ascii=False,
    )
    prod_json = json.dumps([int(p) for p in (product_ids or []) if int(p) > 0])

    with get_conn(paths.db_file) as conn:
        cur = conn.execute(
            """
            INSERT INTO localize_projects (
                workspace_id, title, mode, source_url, source_media_path,
                source_trend_id, source_video_id, source_lang, target_lang,
                hardsub_mode, hardsub_box_json, anti_dup_json, product_ids_json,
                style_preset, aspect_ratio, voice_id,
                whisper_size, translation_style, clone_source_voice, clone_consent_confirmed
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(workspace_id),
                clean_title,
                mode.strip(),
                source_url.strip(),
                source_media_path.strip(),
                int(source_trend_id) if source_trend_id else None,
                int(source_video_id) if source_video_id else None,
                (source_lang or "auto").strip(),
                (target_lang or "vi").strip(),
                clean_hardsub,
                box_json,
                anti_json,
                prod_json,
                (style_preset or "tiktok_karaoke").strip(),
                (aspect_ratio or "9:16").strip(),
                (voice_id or "vi-VN-HoaiMyNeural").strip(),
                clean_whisper,
                clean_style,
                1 if clone_source_voice else 0,
                1 if clone_consent_confirmed else 0,
            ),
        )
        proj_id = int(cur.lastrowid)
        record_audit(
            conn,
            actor=actor,
            action="create_localize_project",
            object_type="localize_project",
            object_id=proj_id,
            detail=f"{mode} -> {target_lang} ({clean_hardsub}, style={clean_style}, clone={bool(clone_source_voice)})",
        )
        if clone_source_voice:
            record_audit(
                conn,
                actor=actor,
                action="enable_source_voice_clone",
                object_type="localize_project",
                object_id=proj_id,
                detail=f"ws={workspace_id} consent_confirmed=True",
            )
    proj = get_localize_project(paths.db_file, proj_id)
    assert proj is not None
    return proj


def _hydrate_project(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out["hardsub_box"] = loads_or(row.get("hardsub_box_json"), {"x": 0.06, "y": 0.74, "w": 0.88, "h": 0.16})
    out["anti_dup"] = loads_or(row.get("anti_dup_json"), {"mirror": False, "zoom": 1.04, "color_eq": True})
    out["segments"] = loads_or(row.get("segments_json"), [])
    out["product_ids"] = loads_or(row.get("product_ids_json"), [])
    out["simulation_flags"] = loads_or(row.get("simulation_flags_json"), [])
    out["speaker_config"] = loads_or(row.get("speaker_config_json"), {})
    out["ocr_cues"] = loads_or(row.get("ocr_cues_json"), [])
    out["clone_source_voice"] = bool(int(row.get("clone_source_voice") or 0))
    out["clone_consent_confirmed"] = bool(int(row.get("clone_consent_confirmed") or 0))
    out["whisper_size"] = str(row.get("whisper_size") or "small")
    out["translation_style"] = str(row.get("translation_style") or "natural_tiktok")
    return out


def get_localize_project(db_file: Path, project_id: int) -> dict[str, Any] | None:
    row = query_one(
        db_file, "SELECT * FROM localize_projects WHERE id = ?", (int(project_id),)
    )
    return _hydrate_project(row) if row else None


def list_localize_projects(db_file: Path, *, workspace_id: int) -> list[dict[str, Any]]:
    rows = query_all(
        db_file,
        "SELECT * FROM localize_projects WHERE workspace_id = ? ORDER BY id DESC LIMIT 100",
        (int(workspace_id),),
    )
    return [_hydrate_project(r) for r in rows]


def update_localize_project(
    paths: AppPaths,
    project_id: int,
    *,
    title: str | None = None,
    target_lang: str | None = None,
    hardsub_mode: str | None = None,
    hardsub_box: dict[str, float] | None = None,
    anti_dup: dict[str, Any] | None = None,
    segments: list[dict[str, Any]] | None = None,
    product_ids: list[int] | None = None,
    style_preset: str | None = None,
    aspect_ratio: str | None = None,
    voice_id: str | None = None,
    whisper_size: str | None = None,
    translation_style: str | None = None,
    clone_source_voice: bool | None = None,
    clone_consent_confirmed: bool | None = None,
    speaker_config: dict[str, Any] | None = None,
    actor: str = "api",
) -> dict[str, Any] | None:
    existing = get_localize_project(paths.db_file, project_id)
    if existing is None:
        return None

    eff_clone = existing["clone_source_voice"] if clone_source_voice is None else bool(clone_source_voice)
    eff_consent = (
        existing["clone_consent_confirmed"]
        if clone_consent_confirmed is None
        else bool(clone_consent_confirmed)
    )
    validate_localize_policy(
        paths.db_file,
        int(existing["workspace_id"]),
        str(existing["mode"]),
        clone_source_voice=eff_clone,
        clone_consent_confirmed=eff_consent,
    )

    sets: list[str] = ["updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"]
    params: list[Any] = []
    if title is not None and title.strip():
        sets.append("title = ?")
        params.append(title.strip())
    if target_lang is not None and target_lang.strip():
        sets.append("target_lang = ?")
        params.append(target_lang.strip())
    if hardsub_mode is not None:
        sets.append("hardsub_mode = ?")
        params.append(_normalize_hardsub_mode(hardsub_mode))
    if hardsub_box is not None:
        sets.append("hardsub_box_json = ?")
        params.append(json.dumps(hardsub_box, ensure_ascii=False))
    if anti_dup is not None:
        sets.append("anti_dup_json = ?")
        params.append(json.dumps(anti_dup, ensure_ascii=False))
    if segments is not None:
        t_lang = (target_lang or str(existing.get("target_lang") or "vi")).strip()
        recomputed: list[dict[str, Any]] = []
        for idx, s in enumerate(segments):
            st = float(s.get("start_s") or 0.0)
            en = max(st + 0.4, float(s.get("end_s") or (st + 1.5)))
            tr_txt = str(s.get("translated_text") or "")
            recomputed.append(
                {
                    **s,
                    "index": idx,
                    "syllable_count": count_syllables(tr_txt, t_lang),
                    "syllable_budget": max_syllables_for_duration(en - st, t_lang),
                }
            )
        sets.append("segments_json = ?")
        params.append(json.dumps(recomputed, ensure_ascii=False))
    if product_ids is not None:
        sets.append("product_ids_json = ?")
        params.append(json.dumps([int(p) for p in product_ids if int(p) > 0]))
    if style_preset is not None and style_preset.strip():
        sets.append("style_preset = ?")
        params.append(style_preset.strip())
    if aspect_ratio is not None and aspect_ratio.strip():
        sets.append("aspect_ratio = ?")
        params.append(aspect_ratio.strip())
    if voice_id is not None and voice_id.strip():
        sets.append("voice_id = ?")
        params.append(voice_id.strip())
    if whisper_size is not None:
        cw = whisper_size.strip().lower()
        if cw not in VALID_WHISPER_SIZES:
            raise ValueError(f"Unsupported whisper_size '{whisper_size}'")
        sets.append("whisper_size = ?")
        params.append(cw)
    if translation_style is not None:
        cs = translation_style.strip().lower()
        if cs not in VALID_TRANSLATION_STYLES:
            raise ValueError(f"Unsupported translation_style '{translation_style}'")
        sets.append("translation_style = ?")
        params.append(cs)
    if clone_source_voice is not None:
        sets.append("clone_source_voice = ?")
        params.append(1 if eff_clone else 0)
    if clone_consent_confirmed is not None:
        sets.append("clone_consent_confirmed = ?")
        params.append(1 if eff_consent else 0)
    if speaker_config is not None:
        sets.append("speaker_config_json = ?")
        params.append(json.dumps(speaker_config, ensure_ascii=False))

    params.append(int(project_id))
    with get_conn(paths.db_file) as conn:
        conn.execute(
            f"UPDATE localize_projects SET {', '.join(sets)} WHERE id = ?",
            params,
        )
        if clone_source_voice and not existing["clone_source_voice"]:
            record_audit(
                conn,
                actor=actor,
                action="enable_source_voice_clone",
                object_type="localize_project",
                object_id=int(project_id),
                detail=f"ws={existing['workspace_id']} consent_confirmed={eff_consent}",
            )
    return get_localize_project(paths.db_file, project_id)


def _resolve_source_media(paths: AppPaths, proj: dict[str, Any]) -> Path:
    src_rel = str(proj.get("source_media_path") or "").strip()
    if src_rel:
        cand = Path(src_rel)
        if not cand.is_absolute():
            cand = paths.media_dir / src_rel
        if cand.exists():
            return cand

    vid_id = proj.get("source_video_id")
    if vid_id:
        v_row = query_one(
            paths.db_file,
            "SELECT output_path FROM videos WHERE id = ?",
            (int(vid_id),),
        )
        if v_row and v_row.get("output_path"):
            p = paths.media_dir / str(v_row["output_path"])
            if p.exists():
                return p

    trend_id = proj.get("source_trend_id")
    if trend_id:
        ref_row = query_one(
            paths.db_file,
            "SELECT path FROM reference_videos WHERE trend_item_id = ? AND deleted_at IS NULL",
            (int(trend_id),),
        )
        if ref_row and ref_row.get("path"):
            p = paths.media_dir / str(ref_row["path"])
            if p.exists():
                return p
        dl = fetch_reference_video(paths, int(trend_id), ignore_daily_cap=True)
        if dl is not None and dl.exists():
            return dl

    raise FileNotFoundError(
        f"Localize project #{proj['id']} has no available source video on disk"
    )


def _pick_workspace_product_shots(
    db_file: Path, workspace_id: int, product_ids: list[int]
) -> list[int]:
    rows = query_all(
        db_file,
        """
        SELECT s.id, s.has_product, s.product_ids_json, s.quality
        FROM shots s
        LEFT JOIN footage f ON s.footage_id = f.id
        LEFT JOIN assets a ON s.asset_id = a.id
        WHERE COALESCE(f.workspace_id, a.workspace_id, 1) = ?
        ORDER BY s.has_product DESC, s.quality DESC, s.id ASC
        """,
        (int(workspace_id),),
    )
    if not product_ids:
        return [int(r["id"]) for r in rows]
    wanted = {int(pid) for pid in product_ids}
    matched: list[int] = []
    fallback: list[int] = []
    for r in rows:
        pids = set(int(x) for x in loads_or(r.get("product_ids_json"), []) if str(x).isdigit())
        if pids & wanted:
            matched.append(int(r["id"]))
        elif int(r.get("has_product") or 0) == 1:
            fallback.append(int(r["id"]))
    return matched or fallback or [int(r["id"]) for r in rows]


def _set_project_status(
    db_file: Path, project_id: int, status: str, *, error: str | None = None
) -> None:
    with get_conn(db_file) as conn:
        conn.execute(
            """
            UPDATE localize_projects
            SET status = ?, error = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
            WHERE id = ?
            """,
            (status, error, int(project_id)),
        )


def run_localize_extract(
    paths: AppPaths,
    project_id: int,
    *,
    provider_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Runs MDX-Net stem separation, RapidOCR + Faster-Whisper alignment, CPU diarization & AI/NLLB translation."""
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
    _set_project_status(paths.db_file, project_id, "extracting", error=None)

    try:
        src_mp4 = _resolve_source_media(paths, proj)
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
                ocr_cues = extract_hardsub_ocr_cues(src_mp4, sample_every_s=0.5)

            # Check sidecar SRT/VTT on src_mp4 first; otherwise transcribe isolated vocal track when MDX ran
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

        diarized_segments, speaker_cfg, used_diar = diarize_segments_on_cpu(
            paths,
            vocal_wav,
            raw_segments,
            speakers_dir=proj_dir / "speakers",
            media_root=paths.media_dir,
        )
        if not used_diar and not proj.get("source_video_id"):
            sim_flags.append("diarization_single_speaker_fallback")

        # Preserve default project voice_id on SPK_1 when single speaker
        default_voice = str(proj.get("voice_id") or "vi-VN-HoaiMyNeural").strip()
        if len(speaker_cfg) == 1 and "SPK_1" in speaker_cfg and default_voice:
            speaker_cfg["SPK_1"]["voice_id"] = default_voice

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
            _pick_workspace_product_shots(
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
            if mode == "hybrid_remix" and shots_pool and idx == len(translated_segments) - 1 and replace_shot_id == 0:
                replace_shot_id = shots_pool[idx % len(shots_pool)]
            segments.append({**seg, "index": idx, "replace_shot_id": replace_shot_id})

        # Update project union hardsub_box from detected OCR cues if available
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
                    json.dumps({"speakers": speaker_cfg, "trans_engine": trans_engine}, ensure_ascii=False),
                    json.dumps(ocr_cues, ensure_ascii=False),
                    json.dumps(next_box, ensure_ascii=False),
                    json.dumps(sim_flags, ensure_ascii=False),
                    int(project_id),
                ),
            )
        updated = get_localize_project(paths.db_file, project_id)
        assert updated is not None
        return updated
    except Exception as exc:
        _set_project_status(paths.db_file, project_id, "failed", error=str(exc))
        raise


def _clamp_box_pixels(
    box: dict[str, Any], src_w: int, src_h: int, *, inset: int = 0
) -> tuple[int, int, int, int]:
    bx = max(inset, min(src_w - 16 - inset, (int(src_w * float(box.get("x", 0.06))) // 2) * 2))
    by = max(inset, min(src_h - 16 - inset, (int(src_h * float(box.get("y", 0.74))) // 2) * 2))
    bw = max(16, min(src_w - bx - inset, (int(src_w * float(box.get("w", 0.88))) // 2) * 2))
    bh = max(16, min(src_h - by - inset, (int(src_h * float(box.get("h", 0.16))) // 2) * 2))
    return bx, by, bw, bh


def _anti_dup_filter_steps(anti_dup: dict[str, Any], mode: str) -> list[str]:
    if mode != "reup_vi":
        return []
    steps: list[str] = []
    if anti_dup.get("mirror"):
        steps.append("hflip")
    zoom = float(anti_dup.get("zoom") or 1.0)
    if zoom > 1.005:
        z = min(1.25, max(1.01, zoom))
        steps.append(f"crop=trunc(iw/{z:.3f}/2)*2:trunc(ih/{z:.3f}/2)*2")
    if anti_dup.get("color_eq", True):
        steps.append("eq=contrast=1.03:saturation=1.04")
    return steps


def _boxes_for_segment_window(
    seg: dict[str, Any],
    ocr_cues: list[dict[str, Any]],
    fallback_box: dict[str, Any],
) -> tuple[list[dict[str, float]], bool]:
    """Resolves active hardsub bounding boxes for `[seg.start_s, seg.end_s]`."""
    st = float(seg.get("start_s") or 0.0)
    en = float(seg.get("end_s") or (st + 1.5))
    matched: list[dict[str, float]] = []
    for cue in ocr_cues:
        c_st = float(cue.get("start_s") or 0.0)
        c_en = float(cue.get("end_s") or 0.0)
        if min(en + 0.12, c_en) - max(st - 0.12, c_st) > 0.08 and isinstance(cue.get("box"), dict):
            matched.append(dict(cue["box"]))
    if matched:
        return matched, True
    if isinstance(seg.get("hardsub_box"), dict):
        return [dict(seg["hardsub_box"])], True
    if ocr_cues:
        # OCR ran and found cues elsewhere in the video, so this segment genuinely has no hardsub
        return [], False
    return [dict(fallback_box)], True


def _cut_localized_segment(
    paths: AppPaths,
    src_mp4: Path,
    seg_path: Path,
    *,
    start_s: float,
    duration_s: float,
    src_duration_s: float,
    src_w: int,
    src_h: int,
    canvas_w: int,
    canvas_h: int,
    hardsub_mode: str,
    active_boxes: list[dict[str, float]],
    fallback_box: dict[str, Any],
    anti_dup: dict[str, Any],
    mode: str,
    work_dir: Path,
) -> bool:
    """Cuts & processes hardsubs on a single segment. Returns `True` if LaMa ONNX ran (when `ocr_inpaint`)."""
    anti_steps = _anti_dup_filter_steps(anti_dup, mode)
    scale_tail = (
        f"scale={canvas_w}:{canvas_h}:force_original_aspect_ratio=decrease,"
        f"pad={canvas_w}:{canvas_h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps=30,format=yuv420p"
    )
    need_loop = start_s + duration_s > max(0.5, src_duration_s - 0.05)
    seek_s = 0.0 if start_s >= max(0.0, src_duration_s - 0.25) else start_s

    input_args: list[str] = []
    if need_loop:
        input_args.extend(["-stream_loop", "-1"])
    input_args.extend(["-ss", f"{seek_s:.3f}", "-t", f"{duration_s:.3f}", "-i", str(src_mp4.resolve())])
    extra_meta = ["-map_metadata", "-1"] if mode == "reup_vi" else []

    # High-Quality LaMa ONNX Inpaint mode when `ocr_inpaint` is selected and `paddle_lama_inpaint` is ready
    if hardsub_mode == "ocr_inpaint" and active_boxes:
        lama_info = get_local_model(paths, "paddle_lama_inpaint")
        if lama_info and lama_info.get("status") == "ready" and lama_info.get("installed_on_disk"):
            raw_clip = work_dir / f"_raw_{seg_path.name}"
            inpainted_clip = work_dir / f"_inp_{seg_path.name}"
            run_ffmpeg(
                [
                    *input_args,
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "16",
                    "-pix_fmt",
                    "yuv420p",
                    "-r",
                    "30",
                    "-an",
                    str(raw_clip.resolve()),
                ],
                cwd=work_dir,
            )
            ok_lama = inpaint_segment_with_lama(
                paths,
                raw_clip,
                inpainted_clip,
                boxes=active_boxes,
                work_dir=work_dir,
            )
            raw_clip.unlink(missing_ok=True)
            if ok_lama and inpainted_clip.is_file():
                vf_post = [*anti_steps, scale_tail]
                run_ffmpeg(
                    [
                        "-i",
                        str(inpainted_clip.resolve()),
                        "-vf",
                        ",".join(vf_post),
                        "-c:v",
                        "libx264",
                        "-preset",
                        "veryfast",
                        "-crf",
                        "16",
                        "-pix_fmt",
                        "yuv420p",
                        "-r",
                        "30",
                        "-an",
                        *extra_meta,
                        str(seg_path.resolve()),
                    ],
                    cwd=work_dir,
                    allow_creative_filters=bool(anti_steps),
                )
                inpainted_clip.unlink(missing_ok=True)
                return True
            inpainted_clip.unlink(missing_ok=True)

    # Merge active_boxes into union box for blur_bar / delogo
    union_box: dict[str, Any] | None = None
    if active_boxes:
        x1 = min(float(b["x"]) for b in active_boxes)
        y1 = min(float(b["y"]) for b in active_boxes)
        x2 = max(float(b["x"]) + float(b["w"]) for b in active_boxes)
        y2 = max(float(b["y"]) + float(b["h"]) for b in active_boxes)
        union_box = {"x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1}

    if hardsub_mode == "blur_bar" and union_box is not None:
        bx, by, bw, bh = _clamp_box_pixels(union_box, src_w, src_h, inset=0)
        luma_r = max(2, min(16, min(bw, bh) // 4 - 1))
        chroma_r = max(1, min(8, min(bw, bh) // 8 - 1))
        anti_chain = ("," + ",".join(anti_steps)) if anti_steps else ""
        fc = (
            f"[0:v]split[base][sub];"
            f"[sub]crop={bw}:{bh}:{bx}:{by},boxblur={luma_r}:2:{chroma_r}:1,"
            f"drawbox=x=0:y=0:w=iw:h=ih:color=black@0.48:t=fill[blurred];"
            f"[base][blurred]overlay={bx}:{by}{anti_chain},{scale_tail}[vout]"
        )
        filter_args = ["-filter_complex", fc, "-map", "[vout]"]
    else:
        vf_steps: list[str] = []
        if hardsub_mode == "crop_frame":
            ref_b = union_box or fallback_box
            norm_y = float(ref_b.get("y", 0.74))
            norm_h = float(ref_b.get("h", 0.16))
            if norm_y >= 0.48:
                keep_h = max(32, (int(src_h * max(0.35, min(0.92, norm_y))) // 2) * 2)
                vf_steps.append(f"crop=iw:{keep_h}:0:0")
            else:
                cut_top = (int(src_h * min(0.55, norm_y + norm_h)) // 2) * 2
                keep_h = max(32, ((src_h - cut_top) // 2) * 2)
                vf_steps.append(f"crop=iw:{keep_h}:0:{cut_top}")
        elif hardsub_mode == "ocr_inpaint" and union_box is not None:
            bx, by, bw, bh = _clamp_box_pixels(union_box, src_w, src_h, inset=2)
            vf_steps.append(f"delogo=x={bx}:y={by}:w={bw}:h={bh}:show=0")
        vf_steps.extend(anti_steps)
        vf_steps.append(scale_tail)
        filter_args = ["-vf", ",".join(vf_steps), "-map", "0:v:0"]

    run_ffmpeg(
        [
            *input_args,
            *filter_args,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "16",
            "-pix_fmt",
            "yuv420p",
            "-r",
            "30",
            "-an",
            *extra_meta,
            str(seg_path.resolve()),
        ],
        cwd=work_dir,
        allow_creative_filters=(hardsub_mode != "none" or bool(anti_steps)),
    )
    return False


def _cut_real_product_shot_segment(
    paths: AppPaths,
    shot_id: int,
    seg_path: Path,
    *,
    duration_s: float,
    canvas_w: int,
    canvas_h: int,
    work_dir: Path,
) -> None:
    """Cuts a real `shots` clip strictly under BR-PRD-01 whitelist (zero creative/color filters)."""
    shot_row, src_file = _load_shot_source(paths, shot_id)
    start_s = max(0.0, float(shot_row.get("start_s") or 0.0))
    src_dur = max(0.5, probe_duration(src_file))
    try:
        crop_cfg = json.loads(shot_row["crop_json"]) if shot_row.get("crop_json") else None
    except Exception:
        crop_cfg = None
    raw_focus = shot_row.get("focus_x")
    focus_x = float(raw_focus) if raw_focus is not None else None
    filter_args = build_segment_filter_args(
        orientation=str(shot_row.get("orientation") or "portrait"),
        width=int(shot_row.get("width") or 1080),
        height=int(shot_row.get("height") or 1920),
        crop_cfg=crop_cfg,
        focus_x=focus_x,
        target_width=canvas_w,
        target_height=canvas_h,
    )
    video_map = [] if filter_args[0] == "-filter_complex" else ["-map", "0:v:0"]
    in_args: list[str] = []
    if start_s + duration_s > max(0.5, src_dur - 0.05):
        in_args.extend(["-stream_loop", "-1"])
        start_s = 0.0 if start_s >= src_dur - 0.25 else start_s
    in_args.extend(["-ss", f"{start_s:.3f}", "-t", f"{duration_s:.3f}", "-i", str(src_file.resolve())])

    run_ffmpeg(
        [
            *in_args,
            *filter_args,
            *video_map,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "14",
            "-pix_fmt",
            "yuv420p",
            "-r",
            "30",
            "-an",
            str(seg_path.resolve()),
        ],
        cwd=work_dir,
        allow_creative_filters=False,
    )


def _resolve_segment_voice_spec(
    paths: AppPaths,
    proj: dict[str, Any],
    seg: dict[str, Any],
    *,
    requested_provider: str,
) -> tuple[str, str, Path | None]:
    """Resolves `(provider, voice_id, ref_audio_path)` for a segment based on speaker map & clone policy."""
    req = (requested_provider or "auto").strip().lower()
    if req in ("test_tone", "local"):
        return "test_tone", str(proj.get("voice_id") or "vi-VN-HoaiMyNeural"), None

    spk_id = str(seg.get("speaker_id") or "SPK_1")
    speakers_map = dict((proj.get("speaker_config") or {}).get("speakers") or {})
    spk_entry = dict(speakers_map.get(spk_id) or {})

    target_lang = str(proj.get("target_lang") or "vi").strip().lower()
    clone_enabled = bool(proj.get("clone_source_voice")) and bool(proj.get("clone_consent_confirmed"))

    # Original speaker cloning via VieNeu-TTS v3 Nano (Vietnamese target, project-scoped ref clip)
    if clone_enabled and target_lang.startswith("vi"):
        ref_rel = str(spk_entry.get("ref_audio_rel") or "").strip()
        if ref_rel:
            ref_abs = paths.media_dir / ref_rel
            # Security check: ensure ref_abs stays inside this project's speakers folder
            proj_spk_root = (paths.media_dir / "localize" / f"proj_{proj['id']}" / "speakers").resolve()
            if ref_abs.is_file() and proj_spk_root in ref_abs.resolve().parents:
                vieneu_m = get_local_model(paths, "vieneu_tts_vi")
                if vieneu_m and vieneu_m.get("status") == "ready" and vieneu_m.get("installed_on_disk"):
                    return "vieneu", "Minh Quân", ref_abs

    if req in ("edge", "vieneu"):
        prov = req
    else:
        prov = str(spk_entry.get("provider") or "edge").strip().lower()

    voice_id = str(seg.get("voice_id") or spk_entry.get("voice_id") or proj.get("voice_id") or "").strip()
    if prov == "vieneu":
        vieneu_m = get_local_model(paths, "vieneu_tts_vi")
        if not (vieneu_m and vieneu_m.get("status") == "ready" and vieneu_m.get("installed_on_disk")):
            prov = "edge"
            voice_id = "vi-VN-HoaiMyNeural"
        elif not voice_id or voice_id.startswith(("vi-VN-", "en-US-")):
            voice_id = "Minh Quân"
    else:
        prov = "edge"
        if not voice_id or not ("-" in voice_id and "Neural" in voice_id):
            voice_id = "en-US-JennyNeural" if target_lang.startswith("en") else "vi-VN-HoaiMyNeural"

    return prov, voice_id, None


def preview_localize_segment_audio(
    paths: AppPaths,
    project_id: int,
    segment_index: int,
    *,
    tts_provider: str = "auto",
) -> dict[str, Any]:
    """Synthesizes a single segment preview WAV for `/localize` inline playback."""
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
    segments = list(proj.get("segments") or [])
    if segment_index < 0 or segment_index >= len(segments):
        raise ValueError(f"Segment index {segment_index} out of range")

    seg = segments[segment_index]
    txt = str(seg.get("translated_text") or seg.get("source_text") or "").strip()
    if not txt:
        raise ValueError("Đoạn thoại trống, không thể nghe thử")

    dur_s = max(0.6, float(seg.get("end_s", 2.0)) - float(seg.get("start_s", 0.0)))
    prov, voice_id, ref_audio = _resolve_segment_voice_spec(
        paths, proj, seg, requested_provider=tts_provider
    )
    preview_dir = paths.media_dir / "localize" / f"proj_{project_id}" / "previews"
    work_dir = paths.work_dir / f"loc_preview_{project_id}_{segment_index}"
    try:
        track, prev_paths, _warns = synthesize_timed_speaker_segments(
            paths,
            [
                {
                    "text": txt,
                    "offset_s": 0.0,
                    "duration_s": dur_s,
                    "provider": prov,
                    "voice": voice_id,
                    "ref_audio": ref_audio,
                }
            ],
            work_dir=work_dir,
            preview_out_dir=preview_dir,
        )
        out_wav = Path(prev_paths[0]) if prev_paths and prev_paths[0] else track.audio_path
        dst_wav = preview_dir / f"seg_{segment_index:03d}.wav"
        if out_wav.resolve() != dst_wav.resolve():
            shutil.copy2(out_wav, dst_wav)
        rel = str(dst_wav.relative_to(paths.media_dir)).replace("\\", "/")
        return {
            "segment_index": segment_index,
            "audio_url": f"/files/{rel}",
            "duration_s": round(probe_duration(dst_wav), 3),
            "provider": track.provider,
            "voice_id": voice_id,
            "cloned": ref_audio is not None,
        }
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def run_localize_render(
    paths: AppPaths,
    project_id: int,
    *,
    tts_provider: str = "auto",
    target_accounts: list[int] | None = None,
    auto_approve: bool = True,
) -> dict[str, Any]:
    """Renders localized/remixed video using dynamic OCR/LaMa hardsub removal, multi-speaker TTS & QC."""
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

    _set_project_status(paths.db_file, project_id, "rendering", error=None)
    work_dir = paths.work_dir / f"localize_{project_id}"
    if work_dir.exists():
        shutil.rmtree(work_dir, ignore_errors=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    try:
        src_mp4 = _resolve_source_media(paths, proj)
        src_info = probe_video(src_mp4)
        src_w, src_h = max(64, src_info.width), max(64, src_info.height)
        src_dur = max(0.5, src_info.duration_s)

        aspect_ratio = str(proj.get("aspect_ratio") or "9:16")
        canvas_w, canvas_h = resolve_canvas_dimensions(aspect_ratio)
        style_row = resolve_style_preset(paths.db_file, str(proj.get("style_preset") or "tiktok_karaoke"))
        hardsub_mode = _normalize_hardsub_mode(str(proj.get("hardsub_mode") or "blur_bar"))
        ocr_cues = list(proj.get("ocr_cues") or [])
        fallback_box = dict(proj.get("hardsub_box") or {"x": 0.06, "y": 0.74, "w": 0.88, "h": 0.16})

        seg_files: list[str] = []
        raw_sub_specs: list[dict[str, Any]] = []
        timed_tts_items: list[dict[str, Any]] = []
        cursor_s = 0.0
        used_shot_ids: list[int] = []
        any_lama_used = False
        any_inpaint_needed = False
        any_cloned_used = False

        for idx, seg in enumerate(segments, start=1):
            st = max(0.0, float(seg.get("start_s") or 0.0))
            en = max(st + 0.5, float(seg.get("end_s") or (st + 1.5)))
            dur_s = round(en - st, 3)
            seg_name = f"loc_seg_{idx:02d}.mp4"
            seg_path = work_dir / seg_name

            rep_shot = int(seg.get("replace_shot_id") or 0)
            if mode == "hybrid_remix" and rep_shot > 0:
                _cut_real_product_shot_segment(
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
                active_boxes, has_sub = _boxes_for_segment_window(seg, ocr_cues, fallback_box)
                if hardsub_mode == "ocr_inpaint" and has_sub:
                    any_inpaint_needed = True
                used_lama = _cut_localized_segment(
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
            main_txt = str(seg.get("translated_text") or seg.get("source_text") or "").strip() or "Video"
            sec_txt = str(seg.get("source_text") or "").strip()
            prov, v_id, ref_audio = _resolve_segment_voice_spec(
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

        try:
            voice_track, preview_paths, _warnings = synthesize_timed_speaker_segments(
                paths,
                timed_tts_items,
                work_dir=work_dir / "tts",
                preview_out_dir=preview_dir,
            )
            if any(t in voice_track.provider for t in ("test_tone", "local")) and "tts_tone_placeholder" not in sim_flags:
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

        # Attach karaoke word tuples `(word, start_s, end_s)` from real TTS word timings onto each SubtitleEvent!
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
                    rel_prev = str(Path(preview_paths[idx]).relative_to(paths.media_dir)).replace("\\", "/")
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
        render_cache = _save_render_cache(
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

        done_proj = get_localize_project(paths.db_file, project_id)
        assert done_proj is not None
        return done_proj
    except Exception as exc:
        _set_project_status(paths.db_file, project_id, "failed", error=str(exc))
        raise
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def run_localize_extract_job(paths: AppPaths, project_id: int) -> str:
    proj = run_localize_extract(paths, project_id)
    return str(proj.get("status") or "ready_to_edit")


def run_localize_render_job(paths: AppPaths, project_id: int) -> str:
    proj = run_localize_render(paths, project_id)
    return str(proj.get("status") or "completed")

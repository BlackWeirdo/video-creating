"""Localize project CRUD, workspace content-policy checks, and source media resolution."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from videocreator.db import get_conn, query_all, query_one, record_audit
from videocreator.db_rows import hydrate_row
from videocreator.jsonutil import loads_or
from videocreator.paths import AppPaths
from videocreator.trends.download import fetch_reference_video
from videocreator.tts.syllables import count_syllables, max_syllables_for_duration
from videocreator.workspaces import require_workspace

VALID_LOCALIZE_MODES: frozenset[str] = frozenset({"reup_vi", "hybrid_remix", "intl_export"})
VALID_HARDSUB_MODES: frozenset[str] = frozenset(
    {"none", "blur_bar", "crop_frame", "ocr_inpaint", "lama_inpaint"}
)
VALID_WHISPER_SIZES: frozenset[str] = frozenset({"small", "medium"})
VALID_TRANSLATION_STYLES: frozenset[str] = frozenset({"natural_tiktok", "literal"})


def normalize_hardsub_mode(raw_mode: str) -> str:
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
    """Enforce workspace `content_policy` and Decision 7c voice-cloning safeguards."""
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


def hydrate_project(row: dict[str, Any]) -> dict[str, Any]:
    out = hydrate_row(
        row,
        json_fields={
            "hardsub_box": ("hardsub_box_json", {"x": 0.06, "y": 0.74, "w": 0.88, "h": 0.16}),
            "anti_dup": ("anti_dup_json", {"mirror": False, "zoom": 1.04, "color_eq": True}),
            "segments": ("segments_json", []),
            "product_ids": ("product_ids_json", []),
            "simulation_flags": ("simulation_flags_json", []),
            "speaker_config": ("speaker_config_json", {}),
            "ocr_cues": ("ocr_cues_json", []),
        },
        bool_fields=("clone_source_voice", "clone_consent_confirmed"),
    )
    out["whisper_size"] = str(row.get("whisper_size") or "small")
    out["translation_style"] = str(row.get("translation_style") or "natural_tiktok")
    return out


def get_localize_project(db_file: Path, project_id: int) -> dict[str, Any] | None:
    row = query_one(
        db_file, "SELECT * FROM localize_projects WHERE id = ?", (int(project_id),)
    )
    return hydrate_project(row) if row else None


def list_localize_projects(db_file: Path, *, workspace_id: int) -> list[dict[str, Any]]:
    rows = query_all(
        db_file,
        "SELECT * FROM localize_projects WHERE workspace_id = ? ORDER BY id DESC LIMIT 100",
        (int(workspace_id),),
    )
    return [hydrate_project(r) for r in rows]


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
    clean_hardsub = normalize_hardsub_mode(hardsub_mode)
    clean_whisper = (whisper_size or "small").strip().lower()
    if clean_whisper not in VALID_WHISPER_SIZES:
        raise ValueError(f"Unsupported whisper_size '{whisper_size}'")
    clean_style = (translation_style or "natural_tiktok").strip().lower()
    if clean_style not in VALID_TRANSLATION_STYLES:
        raise ValueError(f"Unsupported translation_style '{translation_style}'")

    clean_title = (title or "").strip()
    if not clean_title:
        raise ValueError("Localize project title is required")

    if (
        str(ws.get("content_policy") or "") == "strict_footage"
        and source_video_id is None
        and not source_media_path
    ):
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

    eff_clone = (
        existing["clone_source_voice"] if clone_source_voice is None else bool(clone_source_voice)
    )
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
        params.append(normalize_hardsub_mode(hardsub_mode))
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


def resolve_source_media(paths: AppPaths, proj: dict[str, Any]) -> Path:
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


def pick_workspace_product_shots(
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


def set_project_status(
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

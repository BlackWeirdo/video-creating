"""Shared dependencies and JSON serialization helpers for `/api/v1` endpoints."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import HTTPException

from videocreator.jsonutil import loads_or, parse_int_list
from videocreator.tts import check_syllable_budget
from videocreator.workspaces import (
    get_active_workspace_id,
    get_workspace,
    require_workspace,
)


def resolve_workspace_id(
    db_file: Path,
    workspace_id: int | None = None,
    *,
    require_active: bool = False,
) -> int:
    """Resolves `workspace_id` (defaulting to active workspace) and enforces workspace validity."""
    ws_id = int(workspace_id) if workspace_id is not None else get_active_workspace_id(db_file)
    try:
        if require_active:
            ws = require_workspace(db_file, ws_id)
            return int(ws["id"])
        ws = get_workspace(db_file, ws_id)
        if ws is None:
            raise HTTPException(status_code=404, detail=f"Workspace {ws_id} not found")
        return int(ws["id"])
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def serialize_v1_video(
    row: dict[str, Any],
    *,
    product_map: dict[int, str] | None = None,
) -> dict[str, Any]:
    plan = loads_or(row.get("plan_json"), {})
    if not isinstance(plan, dict):
        plan = {}
    captions = loads_or(row.get("captions_json"), {})
    if not isinstance(captions, dict):
        captions = {}
    preflight = loads_or(row.get("preflight_json"), {})
    if not isinstance(preflight, dict):
        preflight = {}
    qc = loads_or(row.get("qc_json"), {})
    if not isinstance(qc, dict):
        qc = {}
    render_cache = loads_or(row.get("render_cache_json"), {})
    if not isinstance(render_cache, dict):
        render_cache = {}
    claims = loads_or(row.get("unsupported_claims_json"), [])
    if not isinstance(claims, list):
        claims = []

    pids = parse_int_list(row.get("product_ids_json"))
    target_accounts = parse_int_list(row.get("target_accounts_json"))
    pmap = product_map or {}

    vlang = str(row.get("voice_lang") or "none")
    budget_lang = vlang if vlang in ("vi", "en") else str(row.get("caption_lang") or "vi")
    shots_list = plan.get("shots") if isinstance(plan.get("shots"), list) else []
    syllable_budget = check_syllable_budget(shots_list, lang=budget_lang)

    out_rel = str(row.get("output_path") or "").strip()
    cov_rel = str(row.get("cover_path") or "").strip()

    return {
        "id": int(row["id"]),
        "workspace_id": int(row.get("workspace_id") or 1),
        "footage_id": row.get("footage_id"),
        "product_ids": pids,
        "product_names": [pmap.get(pid, f"#{pid}") for pid in pids],
        "engine": str(row.get("engine") or "ffmpeg"),
        "status": str(row.get("status") or "planned"),
        "style_preset": str(row.get("style_preset") or "tiktok_karaoke"),
        "aspect_ratio": str(row.get("aspect_ratio") or "9:16"),
        "voice_lang": vlang,
        "caption_lang": str(row.get("caption_lang") or "vi"),
        "plan": plan,
        "captions": captions,
        "target_accounts": target_accounts,
        "output_path": out_rel or None,
        "output_url": f"/files/{out_rel}" if out_rel else None,
        "cover_path": cov_rel or None,
        "cover_url": f"/files/{cov_rel}" if cov_rel else None,
        "duration_s": row.get("duration_s"),
        "preflight": preflight,
        "qc": qc,
        "render_cache": render_cache,
        "unsupported_claims": claims,
        "quality_score": row.get("quality_score"),
        "quality_notes": row.get("quality_notes"),
        "suggestion_id": row.get("suggestion_id"),
        "syllable_budget": syllable_budget,
        "error": row.get("error"),
        "reject_reason": row.get("reject_reason"),
        "created_at": str(row.get("created_at") or ""),
        "approved_at": row.get("approved_at"),
        "approved_by": row.get("approved_by"),
    }

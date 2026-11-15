"""The approval queue as shown to the reviewer: pending videos with parsed plan, captions and checks."""
from __future__ import annotations
from pathlib import Path
from typing import Any

from videocreator.db import query_all
from videocreator.jsonutil import loads_or, parse_int_list
from videocreator.products import product_name_map


def video_display_fields(row: dict[str, Any], product_map: dict[int, str]) -> dict[str, Any]:
    """A `videos` row with its JSON columns parsed and the names the pages and messages show."""
    plan = loads_or(row.get("plan_json"), {})
    product_ids = parse_int_list(row.get("product_ids_json"))
    return {
        **row,
        "plan": plan,
        "title": plan.get("title") or f"Video #{row['id']}",
        "formula": plan.get("formula") or "hook-first",
        "product_ids": product_ids,
        "product_names": [product_map.get(pid, f"#{pid}") for pid in product_ids],
        "preflight": loads_or(row.get("preflight_json"), {}),
    }


def _broll_flags(db_file: Path, plan: dict[str, Any]) -> tuple[bool, bool]:
    """`(has_ai_broll, has_stock_broll)`: whether any planned shot is backed by an AI or stock B-roll clip."""
    shot_ids = [int(s["shot_id"]) for s in (plan.get("shots") or []) if "shot_id" in s]
    if not shot_ids:
        return False, False
    placeholders = ",".join("?" for _ in shot_ids)
    broll_rows = query_all(
        db_file,
        f"""
        SELECT s.tags_json, a.kind AS asset_kind, a.meta_json
        FROM shots s
        LEFT JOIN assets a ON s.asset_id = a.id
        WHERE s.id IN ({placeholders})
        """,
        shot_ids,
    )
    has_ai_broll = False
    has_stock_broll = False
    for br in broll_rows:
        tags_str = str(br.get("tags_json") or "")
        meta_str = str(br.get("meta_json") or "")
        if "stock_broll" in tags_str or "stock_broll" in meta_str or "pexels" in meta_str or "pixabay" in meta_str:
            has_stock_broll = True
        if br.get("asset_kind") == "broll" or "ai_broll" in tags_str or "broll" in tags_str:
            has_ai_broll = True
    return has_ai_broll, has_stock_broll


def enrich_approval_video(
    db_file: Path,
    row: dict[str, Any],
    product_map: dict[int, str],
) -> dict[str, Any]:
    item = video_display_fields(row, product_map)
    plan = item["plan"]
    unsupported = loads_or(row.get("unsupported_claims_json"), [])
    # Same order as the posting service: the editable copy in `captions_json` wins over the plan.
    captions = loads_or(row.get("captions_json"), {}) or plan.get("captions") or {}
    has_ai_broll, has_stock_broll = _broll_flags(db_file, plan)
    return {
        **item,
        "captions": captions,
        "unverified_claims": unsupported or plan.get("unverified_claims") or [],
        "has_ai_broll": has_ai_broll,
        "has_stock_broll": has_stock_broll,
        "has_studio_effects": str(row.get("engine") or "") == "studio",
    }


def list_pending_approval_videos(db_file: Path) -> list[dict[str, Any]]:
    product_map = product_name_map(db_file)
    rows = query_all(
        db_file,
        "SELECT * FROM videos WHERE status = 'pending_approval' ORDER BY id DESC",
    )
    return [enrich_approval_video(db_file, r, product_map) for r in rows]

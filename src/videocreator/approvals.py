"""Atomic video approval and rejection service shared by Web UI and Telegram Bot (Phase 06)."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from videocreator.api.routes_products import list_products
from videocreator.config import ScheduleConfig, load_settings
from videocreator.db import get_conn, query_all, query_one
from videocreator.posting.slots import assign_auto_slots_for_video, default_target_account_ids
from videocreator.state import InvalidTransitionError, transition


def approve(
    db_file: Path,
    video_id: int,
    *,
    by: str = "ui",
    target_account_ids: list[int] | None = None,
    config_file: Path | None = None,
    now_dt: datetime | None = None,
    auto_schedule: bool | None = None,
) -> bool:
    """Atomically transitions `video_id` from `pending_approval` to `approved` (and `scheduled` if auto-slot is enabled).

    Returns `True` if this caller won the transition, `False` if the video was already
    approved or rejected by another actor, or raises `InvalidTransitionError` if the
    video is not yet in `pending_approval` (e.g. still `planned` or `rendering`).
    """
    row = query_one(db_file, "SELECT status FROM videos WHERE id = ?", (video_id,))
    if row is None:
        raise LookupError(f"Video #{video_id} not found")
    cur_status = str(row["status"])
    if cur_status in ("approved", "rejected", "scheduled", "posted", "partially_posted"):
        return False
    if cur_status != "pending_approval":
        raise InvalidTransitionError(
            f"Cannot approve video #{video_id} from status '{cur_status}' (must be 'pending_approval')"
        )

    won = transition(
        db_file,
        video_id,
        "approved",
        expected_from="pending_approval",
        actor=by,
        approved_by=by,
    )
    if won and target_account_ids is not None:
        clean_acc = sorted({int(a) for a in target_account_ids if int(a) > 0})
        with get_conn(db_file) as conn:
            conn.execute(
                "UPDATE videos SET target_accounts_json = ? WHERE id = ?",
                (json.dumps(clean_acc), video_id),
            )

    if won:
        sched_cfg = (
            load_settings(config_file).schedule
            if (config_file is not None and config_file.exists())
            else ScheduleConfig()
        )
        should_auto = sched_cfg.auto if auto_schedule is None else auto_schedule
        if should_auto:
            assign_auto_slots_for_video(
                db_file,
                video_id,
                config_file=config_file,
                account_ids=target_account_ids,
                now_dt=now_dt,
                actor=by,
            )
    return won


def reject(
    db_file: Path,
    video_id: int,
    *,
    by: str = "ui",
    reason: str | None = None,
) -> bool:
    """Atomically transitions `video_id` from `pending_approval` to `rejected`."""
    row = query_one(db_file, "SELECT status FROM videos WHERE id = ?", (video_id,))
    if row is None:
        raise LookupError(f"Video #{video_id} not found")
    cur_status = str(row["status"])
    if cur_status in ("approved", "rejected", "scheduled", "posted", "partially_posted"):
        return False
    if cur_status != "pending_approval":
        raise InvalidTransitionError(
            f"Cannot reject video #{video_id} from status '{cur_status}' (must be 'pending_approval')"
        )

    return transition(
        db_file,
        video_id,
        "rejected",
        expected_from="pending_approval",
        actor=by,
        approved_by=by,
        reject_reason=(reason or "").strip() or None,
    )


def enrich_approval_video(
    db_file: Path,
    row: dict[str, Any],
    product_map: dict[int, str],
) -> dict[str, Any]:
    try:
        plan = json.loads(row.get("plan_json") or "{}")
    except Exception:
        plan = {}
    try:
        pids = [int(x) for x in json.loads(row.get("product_ids_json") or "[]")]
    except Exception:
        pids = []
    try:
        preflight = json.loads(row.get("preflight_json") or "{}")
    except Exception:
        preflight = {}
    try:
        unsupported = json.loads(row.get("unsupported_claims_json") or "[]")
    except Exception:
        unsupported = []
    unverified = unsupported or plan.get("unverified_claims") or []
    # Same order as the posting service: the editable copy in `captions_json` wins over the plan.
    try:
        captions = json.loads(str(row.get("captions_json") or "{}"))
    except Exception:
        captions = {}
    if not captions:
        captions = plan.get("captions") or {}

    # Check if any shot in the plan is backed by an AI/stock B-roll asset or tagged as broll
    has_ai_broll = False
    has_stock_broll = False
    shot_ids = [int(s["shot_id"]) for s in (plan.get("shots") or []) if "shot_id" in s]
    if shot_ids:
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
        for br in broll_rows:
            tags_str = str(br.get("tags_json") or "")
            meta_str = str(br.get("meta_json") or "")
            if "stock_broll" in tags_str or "stock_broll" in meta_str or "pexels" in meta_str or "pixabay" in meta_str:
                has_stock_broll = True
            if br.get("asset_kind") == "broll" or "ai_broll" in tags_str or "broll" in tags_str:
                has_ai_broll = True

    has_studio_effects = str(row.get("engine") or "") == "studio"

    return {
        **row,
        "plan": plan,
        "title": plan.get("title") or f"Video #{row['id']}",
        "formula": plan.get("formula") or "hook-first",
        "product_ids": pids,
        "product_names": [product_map.get(pid, f"#{pid}") for pid in pids],
        "captions": captions,
        "preflight": preflight,
        "unverified_claims": unverified,
        "has_ai_broll": has_ai_broll,
        "has_stock_broll": has_stock_broll,
        "has_studio_effects": has_studio_effects,
    }


def list_pending_approval_videos(db_file: Path) -> list[dict[str, Any]]:
    all_products = list_products(db_file, include_hidden=True)
    product_map = {p["id"]: p["name"] for p in all_products}
    rows = query_all(
        db_file,
        "SELECT * FROM videos WHERE status = 'pending_approval' ORDER BY id DESC",
    )
    return [enrich_approval_video(db_file, r, product_map) for r in rows]


def redo_video(
    db_file: Path,
    video_id: int,
    *,
    by: str = "ui",
    is_auto_retry: bool = False,
    max_retries: int = 2,
) -> int | None:
    """Marks `video_id` as `superseded` and queues a replacement with a NEW script (`FR-APR-05`, `FR-APR-06`).

    The replacement row starts with the old plan; the `replan` job writes a different one into it and
    renders it (re-rendering the same plan would give the same video). Studio videos are revised by
    prompt in Studio instead, so they return `None` here.

    `auto_retry_count` (auto quality scoring) and `redo_count` (human reviewer clicking 'Làm lại') are counted separately.
    Returns the new `video_id`, or `None` if the retry limit (`max_retries`, default 2) has been reached or the video was already superseded.
    """
    from videocreator.db import record_audit
    from videocreator.jobs import enqueue_job

    row = query_one(db_file, "SELECT * FROM videos WHERE id = ?", (video_id,))
    if row is None:
        raise LookupError(f"Video #{video_id} not found")

    cur_status = str(row["status"])
    if cur_status not in ("pending_approval", "rendered", "scoring", "planned"):
        return None
    if str(row.get("engine") or "") == "studio":
        return None

    cur_redo = int(row.get("redo_count") or 0)
    cur_auto = int(row.get("auto_retry_count") or 0)
    if is_auto_retry:
        if cur_auto >= max_retries:
            return None
        next_redo = cur_redo
        next_auto = cur_auto + 1
    else:
        if cur_redo >= max_retries:
            return None
        next_redo = cur_redo + 1
        next_auto = cur_auto

    if not transition(
        db_file,
        video_id,
        "superseded",
        expected_from=cur_status,
        actor=by,
    ):
        return None

    with get_conn(db_file) as conn:
        cur = conn.execute(
            """
            INSERT INTO videos (
                footage_id, product_ids_json, engine, status, plan_json,
                voice_lang, caption_lang, captions_json, target_accounts_json,
                redo_count, auto_retry_count, supersedes_id, suggestion_id, auto_render
            )
            VALUES (?, ?, ?, 'planned', ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                row.get("footage_id"),
                row.get("product_ids_json") or "[]",
                row.get("engine") or "ffmpeg",
                row.get("plan_json") or "{}",
                row.get("voice_lang") or "none",
                row.get("caption_lang") or "vi",
                row.get("captions_json"),
                row.get("target_accounts_json"),
                next_redo,
                next_auto,
                video_id,
                row.get("suggestion_id"),
            ),
        )
        new_vid = int(cur.lastrowid or 0)
        record_audit(
            conn,
            actor=by,
            action="video.auto_retried" if is_auto_retry else "video.redone",
            object_type="video",
            object_id=new_vid,
            detail=f"supersedes={video_id}, redo={next_redo}, auto_retry={next_auto}",
        )

    enqueue_job(db_file, "replan", ref_id=new_vid)
    return new_vid


def post_now(
    db_file: Path,
    video_id: int,
    *,
    by: str = "ui",
    now_dt: datetime | None = None,
) -> list[int]:
    """Approves `video_id` (if `pending_approval`) and schedules all target accounts for immediate publishing (`scheduled_at = now`)."""
    from videocreator.posting.service import schedule_approved_video, utc_now_iso

    row = query_one(db_file, "SELECT * FROM videos WHERE id = ?", (video_id,))
    if row is None:
        raise LookupError(f"Video #{video_id} not found")

    if str(row["status"]) == "pending_approval":
        approve(db_file, video_id, by=by, auto_schedule=False)

    target_ids = default_target_account_ids(db_file, video_id)
    if not target_ids:
        return []

    now_iso = utc_now_iso(now_dt)
    post_ids = schedule_approved_video(
        db_file,
        video_id,
        account_ids=target_ids,
        scheduled_at_iso=now_iso,
        actor=by,
    )
    with get_conn(db_file) as conn:
        conn.execute(
            "UPDATE posts SET scheduled_at = ? WHERE video_id = ? AND status = 'scheduled'",
            (now_iso, video_id),
        )
    return post_ids

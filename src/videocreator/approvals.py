"""Atomic video approval and rejection service shared by Web UI and Telegram Bot (Phase 06)."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from videocreator.config import ScheduleConfig, load_settings
from videocreator.db import get_conn, query_one
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


def post_now(
    db_file: Path,
    video_id: int,
    *,
    by: str = "ui",
    now_dt: datetime | None = None,
) -> list[int]:
    """Approves `video_id` (if `pending_approval`) and schedules all target accounts for immediate publishing (`scheduled_at = now`)."""
    from videocreator.posting.service import schedule_approved_video
    from videocreator.timeutil import utc_now_iso

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

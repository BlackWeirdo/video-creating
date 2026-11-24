"""Automatic posting slot calculation per account and timezone (Phase 10)."""
from __future__ import annotations
import json
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from videocreator.config import ScheduleConfig, load_settings
from videocreator.db import get_conn, query_all, query_one, record_audit
from videocreator.jsonutil import loads_or
from videocreator.state import transition
from videocreator.timeutil import UTC_ISO_FORMAT, utc_now


def _parse_hhmm(slot_str: str) -> time | None:
    parts = slot_str.strip().split(":")
    if len(parts) != 2:
        return None
    try:
        h = int(parts[0])
        m = int(parts[1])
        if 0 <= h <= 23 and 0 <= m <= 59:
            return time(hour=h, minute=m, second=0)
    except ValueError:
        return None
    return None


def _account_slot_override(account_row: dict | None) -> list[str]:
    """Valid `HH:MM` slots of the account's own `slots_json`; empty when it has none."""
    if not account_row or not account_row.get("slots_json"):
        return []
    try:
        parsed = json.loads(str(account_row["slots_json"]))
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(s).strip() for s in parsed if _parse_hhmm(str(s)) is not None]


def get_account_slots(
    db_file: Path,
    account_id: int,
    schedule_cfg: ScheduleConfig | None = None,
) -> list[str]:
    """Returns sorted `HH:MM` slots for `account_id` (per-account `slots_json` override or global `schedule.slots`)."""
    cfg = schedule_cfg or ScheduleConfig()
    acc_row = query_one(
        db_file, "SELECT slots_json FROM accounts WHERE id = ?", (account_id,)
    )
    raw_slots = _account_slot_override(acc_row) or list(cfg.slots)
    valid_times = sorted(
        {s.strip() for s in raw_slots if _parse_hhmm(s) is not None},
        key=lambda x: _parse_hhmm(x) or time(0, 0),
    )
    return valid_times or ["08:00", "11:30", "15:00", "19:00", "21:00"]


def next_free_slot(
    db_file: Path,
    account_id: int,
    now_dt: datetime | None = None,
    *,
    config_file: Path | None = None,
) -> datetime:
    """Finds the earliest unoccupied slot after `now_dt` for `account_id`, returned as a UTC `datetime`."""
    sched_cfg = (
        load_settings(config_file).schedule
        if (config_file is not None and config_file.exists())
        else ScheduleConfig()
    )
    tz = ZoneInfo(sched_cfg.timezone)
    base_utc = utc_now(now_dt)
    base_local = base_utc.astimezone(tz)

    slots_hhmm = get_account_slots(db_file, account_id, sched_cfg)
    slot_times = [_parse_hhmm(s) for s in slots_hhmm]
    clean_times = [t for t in slot_times if t is not None]

    # Query existing occupied slots for this account from base_utc - 1 day onwards
    window_start_iso = (base_utc - timedelta(days=1)).strftime(UTC_ISO_FORMAT)
    existing_rows = query_all(
        db_file,
        """
        SELECT scheduled_at
        FROM posts
        WHERE account_id = ?
          AND status IN ('scheduled', 'publishing', 'posted', 'needs_user_action')
          AND scheduled_at >= ?
        """,
        (account_id, window_start_iso),
    )
    occupied_isos = {str(r["scheduled_at"]) for r in existing_rows if r.get("scheduled_at")}

    for day_offset in range(0, 60):
        candidate_date = base_local.date() + timedelta(days=day_offset)
        for t_slot in clean_times:
            cand_local = datetime.combine(candidate_date, t_slot, tzinfo=tz)
            cand_utc = cand_local.astimezone(timezone.utc)
            if cand_utc <= base_utc:
                continue
            cand_iso = cand_utc.strftime(UTC_ISO_FORMAT)
            if cand_iso not in occupied_isos:
                return cand_utc

    return base_utc + timedelta(hours=1)


def default_target_account_ids(db_file: Path, video_id: int) -> list[int]:
    """Target accounts of a video (`FR-APR-02`): the reviewer's selection when there is one, otherwise
    every enabled account whose language matches the captions and whose platform passed the format check."""
    v_row = query_one(
        db_file,
        "SELECT target_accounts_json, caption_lang, preflight_json, workspace_id FROM videos WHERE id = ?",
        (video_id,),
    )
    if v_row is None:
        return []
    try:
        chosen = sorted({int(a) for a in json.loads(str(v_row.get("target_accounts_json") or "[]")) if int(a) > 0})
    except (ValueError, TypeError):
        chosen = []
    if chosen:
        return chosen
    preflight = loads_or(v_row.get("preflight_json"), {})
    ws_id = int(v_row.get("workspace_id") or 1)
    rows = query_all(
        db_file,
        "SELECT id, platform, lang FROM accounts WHERE enabled = 1 AND workspace_id = ? ORDER BY id ASC",
        (ws_id,),
    )
    lang = str(v_row.get("caption_lang") or "vi")
    return [
        int(r["id"])
        for r in rows
        if str(r["lang"]) == lang and not (isinstance(preflight, dict) and preflight.get(str(r["platform"])))
    ]


def assign_auto_slots_for_video(
    db_file: Path,
    video_id: int,
    *,
    config_file: Path | None = None,
    account_ids: list[int] | None = None,
    now_dt: datetime | None = None,
    actor: str = "ui",
) -> list[int]:
    """Assigns each enabled target account to its next free slot and transitions video to `scheduled`."""
    v_row = query_one(
        db_file,
        "SELECT id, status, target_accounts_json FROM videos WHERE id = ?",
        (video_id,),
    )
    if v_row is None:
        raise LookupError(f"Video #{video_id} not found")

    if account_ids:
        target_ids = sorted({int(a) for a in account_ids if int(a) > 0})
    else:
        target_ids = default_target_account_ids(db_file, video_id)

    if not target_ids:
        return []

    created_post_ids: list[int] = []
    with get_conn(db_file) as conn:
        for acc_id in target_ids:
            acc_row = conn.execute(
                "SELECT id, enabled FROM accounts WHERE id = ?", (acc_id,)
            ).fetchone()
            if acc_row is None or not int(acc_row["enabled"]):
                continue
            slot_utc = next_free_slot(
                db_file, acc_id, now_dt=now_dt, config_file=config_file
            )
            slot_iso = slot_utc.strftime(UTC_ISO_FORMAT)
            cur = conn.execute(
                """
                INSERT INTO posts (video_id, account_id, status, scheduled_at)
                VALUES (?, ?, 'scheduled', ?)
                ON CONFLICT(video_id, account_id) DO NOTHING
                """,
                (video_id, acc_id, slot_iso),
            )
            if cur.lastrowid and cur.rowcount == 1:
                created_post_ids.append(int(cur.lastrowid))

        cur_status = str(v_row["status"])
        if cur_status == "approved" and created_post_ids:
            transition(conn, video_id, "scheduled", expected_from="approved", actor=actor)
            record_audit(
                conn,
                actor=actor,
                action="video.auto_scheduled",
                object_type="video",
                object_id=video_id,
                detail=f"posts={created_post_ids}",
            )

    return created_post_ids

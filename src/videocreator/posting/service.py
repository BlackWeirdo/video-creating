"""Posting service state: pause switch, scheduling of approved videos, and R2 staging cleanup (Phase 07)."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from videocreator.db import get_conn, query_all, query_one, record_audit
from videocreator.paths import AppPaths
from videocreator.posting.storage_r2 import delete_from_r2
from videocreator.state import transition
from videocreator.timeutil import utc_now_iso


def is_posting_paused(db_file: Path) -> bool:
    row = query_one(
        db_file, "SELECT value FROM settings WHERE key = 'posting_paused'"
    )
    return bool(row and str(row["value"]).strip() in ("1", "true", "True"))


def set_posting_paused(
    db_file: Path, paused: bool, *, actor: str = "ui"
) -> None:
    val = "1" if paused else "0"
    with get_conn(db_file) as conn:
        conn.execute(
            """
            INSERT INTO settings (key, value) VALUES ('posting_paused', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (val,),
        )
        record_audit(
            conn,
            actor=actor,
            action="posting.paused" if paused else "posting.resumed",
            object_type="settings",
            object_id=None,
            detail=f"posting_paused={val}",
        )


def schedule_approved_video(
    db_file: Path,
    video_id: int,
    *,
    account_ids: list[int],
    scheduled_at_iso: str | None = None,
    actor: str = "ui",
) -> list[int]:
    """Creates `posts` rows for an `approved` (or already `scheduled`) video and transitions video to `scheduled`."""
    v_row = query_one(db_file, "SELECT * FROM videos WHERE id = ?", (video_id,))
    if v_row is None:
        raise LookupError(f"Video #{video_id} not found")

    cur_status = str(v_row["status"])
    if cur_status not in ("approved", "scheduled"):
        raise ValueError(
            f"Video #{video_id} has status '{cur_status}'; only 'approved' videos can be scheduled/posted (FR-APR-01)"
        )

    clean_accs = sorted({int(a) for a in account_ids if int(a) > 0})
    if not clean_accs:
        raise ValueError("Must select at least one target account")

    sched_time = scheduled_at_iso or utc_now_iso()
    created_post_ids: list[int] = []

    with get_conn(db_file) as conn:
        for acc_id in clean_accs:
            acc_row = conn.execute(
                "SELECT id, enabled FROM accounts WHERE id = ?", (acc_id,)
            ).fetchone()
            if acc_row is None or not int(acc_row["enabled"]):
                continue
            cur = conn.execute(
                """
                INSERT INTO posts (video_id, account_id, status, scheduled_at)
                VALUES (?, ?, 'scheduled', ?)
                ON CONFLICT(video_id, account_id) DO NOTHING
                """,
                (video_id, acc_id, sched_time),
            )
            if cur.lastrowid and cur.rowcount == 1:
                created_post_ids.append(int(cur.lastrowid))

        if cur_status == "approved" and created_post_ids:
            transition(conn, video_id, "scheduled", expected_from="approved", actor=actor)
        record_audit(
            conn,
            actor=actor,
            action="video.scheduled",
            object_type="video",
            object_id=video_id,
            detail=f"accounts={clean_accs}, at={sched_time}",
        )

    return created_post_ids


def cleanup_staged_r2_objects(
    paths: AppPaths,
    *,
    now_dt: datetime | None = None,
    deleter: Callable[[str], bool] | None = None,
) -> int:
    """Deletes the public R2 copy of a video 24 hours after all its posts reached a final state (`FR-PST-05`)."""
    cutoff = utc_now_iso((now_dt or datetime.now(timezone.utc)) - timedelta(hours=24))
    rows = query_all(
        paths.db_file,
        """
        SELECT v.id, v.r2_key
        FROM videos v
        WHERE v.r2_key IS NOT NULL AND v.r2_key != ''
          AND NOT EXISTS (
              SELECT 1 FROM posts p WHERE p.video_id = v.id AND p.status IN ('scheduled', 'publishing')
          )
          AND COALESCE(
              (SELECT MAX(COALESCE(p.posted_at, p.next_attempt_at, p.scheduled_at)) FROM posts p WHERE p.video_id = v.id),
              v.created_at
          ) < ?
        """,
        (cutoff,),
    )
    delete = deleter or (lambda key: delete_from_r2(paths, key))
    deleted = 0
    for r in rows:
        if delete(str(r["r2_key"])):
            with get_conn(paths.db_file) as conn:
                conn.execute("UPDATE videos SET r2_key = NULL, r2_url = NULL WHERE id = ?", (int(r["id"]),))
            deleted += 1
    return deleted

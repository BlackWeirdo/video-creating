"""State machine transitions for footage, videos, posts, and jobs."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from videocreator.db import get_conn, record_audit


class InvalidTransitionError(ValueError):
    """Raised when a requested state transition is not permitted by the state machine."""


FOOTAGE_TRANSITIONS: dict[str, set[str]] = {
    "imported": {"analysing"},
    "analysing": {"analysed", "failed"},
    "analysed": {"analysing"},
    "failed": {"analysing"},
}

VIDEO_TRANSITIONS: dict[str, set[str]] = {
    "planned": {"rendering", "superseded"},
    "rendering": {"rendered", "failed", "superseded"},
    "rendered": {"scoring", "pending_approval", "rendering", "superseded"},
    "scoring": {"pending_approval", "failed", "superseded"},
    "pending_approval": {"approved", "rejected", "superseded"},
    "approved": {"scheduled", "posted"},
    "scheduled": {"posted", "failed"},
    "failed": {"rendering", "scheduled", "superseded"},
    "rejected": set(),
    "posted": set(),
    "superseded": set(),
}

POST_TRANSITIONS: dict[str, set[str]] = {
    "scheduled": {"publishing", "missed"},
    "publishing": {"posted", "failed", "needs_user_action", "scheduled"},
    "failed": {"scheduled"},
    "missed": {"scheduled"},
    "needs_user_action": {"posted"},
    "posted": set(),
}

JOB_TRANSITIONS: dict[str, set[str]] = {
    "queued": {"running", "waiting_quota", "failed"},
    "running": {"done", "failed", "waiting_quota", "queued"},
    "waiting_quota": {"queued", "failed"},
    "done": set(),
    "failed": {"queued"},
}

_ALREADY_DECIDED_PAIRS: set[tuple[str, str]] = {
    ("approved", "approved"),
    ("rejected", "rejected"),
    ("approved", "rejected"),
    ("rejected", "approved"),
}


def _run_with_conn(
    db_or_conn: Path | sqlite3.Connection,
    fn: Any,
) -> Any:
    if isinstance(db_or_conn, sqlite3.Connection):
        return fn(db_or_conn)
    with get_conn(db_or_conn) as conn:
        return fn(conn)


def transition(
    db_or_conn: Path | sqlite3.Connection,
    video_id: int,
    to_status: str,
    *,
    expected_from: str | None = None,
    actor: str = "system",
    approved_by: str | None = None,
    reject_reason: str | None = None,
    error: str | None = None,
) -> bool:
    """Atomically transitions a video to `to_status`.

    Returns True if this call won the conditional UPDATE, False if another concurrent
    actor already processed the decision (e.g. duplicate approve/reject), or raises
    InvalidTransitionError if the transition is invalid.
    """
    if expected_from is not None:
        allowed = VIDEO_TRANSITIONS.get(expected_from, set())
        if to_status not in allowed:
            raise InvalidTransitionError(
                f"Invalid video transition: {expected_from} -> {to_status}"
            )

    def _do(conn: sqlite3.Connection) -> bool:
        row = conn.execute(
            "SELECT status FROM videos WHERE id = ?", (video_id,)
        ).fetchone()
        if row is None:
            raise LookupError(f"Video {video_id} does not exist")
        current_status = str(row["status"])

        source_status = expected_from if expected_from is not None else current_status
        if expected_from is not None and current_status != expected_from:
            if (current_status, to_status) in _ALREADY_DECIDED_PAIRS or current_status == to_status:
                return False
            allowed_from_current = VIDEO_TRANSITIONS.get(current_status, set())
            if to_status not in allowed_from_current:
                return False

        if expected_from is None:
            if (current_status, to_status) in _ALREADY_DECIDED_PAIRS:
                return False
            allowed = VIDEO_TRANSITIONS.get(current_status, set())
            if to_status not in allowed:
                raise InvalidTransitionError(
                    f"Invalid video transition: {current_status} -> {to_status}"
                )

        set_clauses = ["status = ?"]
        params: list[Any] = [to_status]

        if to_status == "approved":
            set_clauses.append("approved_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')")
            set_clauses.append("approved_by = ?")
            params.append(approved_by or actor)
        if reject_reason is not None:
            set_clauses.append("reject_reason = ?")
            params.append(reject_reason)
        if error is not None:
            set_clauses.append("error = ?")
            params.append(error)

        params.extend([video_id, source_status])
        sql = f"UPDATE videos SET {', '.join(set_clauses)} WHERE id = ? AND status = ?"
        cur = conn.execute(sql, params)
        if cur.rowcount != 1:
            return False

        record_audit(
            conn,
            actor=approved_by or actor,
            action=f"video.{source_status}_to_{to_status}",
            object_type="video",
            object_id=video_id,
            detail=reject_reason or error,
        )
        return True

    return bool(_run_with_conn(db_or_conn, _do))


def transition_footage(
    db_or_conn: Path | sqlite3.Connection,
    footage_id: int,
    to_status: str,
    *,
    error: str | None = None,
) -> bool:
    def _do(conn: sqlite3.Connection) -> bool:
        row = conn.execute(
            "SELECT status FROM footage WHERE id = ?", (footage_id,)
        ).fetchone()
        if row is None:
            raise LookupError(f"Footage {footage_id} does not exist")
        current = str(row["status"])
        if to_status not in FOOTAGE_TRANSITIONS.get(current, set()):
            raise InvalidTransitionError(
                f"Invalid footage transition: {current} -> {to_status}"
            )
        cur = conn.execute(
            "UPDATE footage SET status = ?, error = ? WHERE id = ? AND status = ?",
            (to_status, error, footage_id, current),
        )
        return cur.rowcount == 1

    return bool(_run_with_conn(db_or_conn, _do))


def transition_post(
    db_or_conn: Path | sqlite3.Connection,
    post_id: int,
    to_status: str,
    *,
    expected_from: str | None = None,
    error: str | None = None,
    external_post_id: str | None = None,
    permalink: str | None = None,
    posted_at: str | None = None,
) -> bool:
    if expected_from is not None:
        if to_status not in POST_TRANSITIONS.get(expected_from, set()):
            raise InvalidTransitionError(
                f"Invalid post transition: {expected_from} -> {to_status}"
            )

    def _do(conn: sqlite3.Connection) -> bool:
        row = conn.execute(
            "SELECT video_id, status FROM posts WHERE id = ?", (post_id,)
        ).fetchone()
        if row is None:
            raise LookupError(f"Post {post_id} does not exist")
        current = str(row["status"])
        video_id = int(row["video_id"])
        source = expected_from if expected_from is not None else current
        if expected_from is not None and current != expected_from:
            return False
        if expected_from is None and to_status not in POST_TRANSITIONS.get(current, set()):
            if current == to_status:
                return False
            raise InvalidTransitionError(
                f"Invalid post transition: {current} -> {to_status}"
            )

        clauses = ["status = ?"]
        params: list[Any] = [to_status]
        if error is not None:
            clauses.append("error = ?")
            params.append(error)
        if external_post_id is not None:
            clauses.append("external_post_id = ?")
            params.append(external_post_id)
        if permalink is not None:
            clauses.append("permalink = ?")
            params.append(permalink)
        if to_status == "posted":
            if posted_at is not None:
                clauses.append("posted_at = ?")
                params.append(posted_at)
            else:
                clauses.append("posted_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')")

        params.extend([post_id, source])
        cur = conn.execute(
            f"UPDATE posts SET {', '.join(clauses)} WHERE id = ? AND status = ?",
            params,
        )
        if cur.rowcount != 1:
            return False

        recompute_video_status_from_posts(conn, video_id)
        return True

    return bool(_run_with_conn(db_or_conn, _do))


def recompute_video_status_from_posts(
    conn: sqlite3.Connection, video_id: int
) -> str | None:
    """Updates video status to 'posted' when all posts are posted/needs_user_action,
    or 'failed' when any post is in permanent 'failed' or 'missed' status."""
    rows = conn.execute(
        "SELECT status FROM posts WHERE video_id = ?", (video_id,)
    ).fetchall()
    if not rows:
        return None
    statuses = [str(r["status"]) for r in rows]
    if any(s in ("failed", "missed") for s in statuses):
        conn.execute(
            "UPDATE videos SET status = 'failed' WHERE id = ? AND status = 'scheduled'",
            (video_id,),
        )
        return "failed"
    if all(s in ("posted", "needs_user_action") for s in statuses):
        conn.execute(
            "UPDATE videos SET status = 'posted' WHERE id = ? AND status IN ('scheduled', 'approved', 'failed')",
            (video_id,),
        )
        return "posted"
    if any(s == "scheduled" for s in statuses):
        conn.execute(
            "UPDATE videos SET status = 'scheduled' WHERE id = ? AND status IN ('approved', 'failed')",
            (video_id,),
        )
        return "scheduled"
    return None

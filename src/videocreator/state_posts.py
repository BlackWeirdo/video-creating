"""Post state machine and the video status derived from its posts."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from videocreator.state import InvalidTransitionError, run_with_conn

POST_TRANSITIONS: dict[str, set[str]] = {
    "scheduled": {"publishing", "missed"},
    "publishing": {"posted", "failed", "needs_user_action", "scheduled"},
    "failed": {"scheduled"},
    "missed": {"scheduled"},
    "needs_user_action": {"posted"},
    "posted": set(),
}


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

    def _apply_transition(conn: sqlite3.Connection) -> bool:
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

    return bool(run_with_conn(db_or_conn, _apply_transition))


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

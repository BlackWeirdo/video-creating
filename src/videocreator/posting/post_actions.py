"""Actions on one existing post: retry, reschedule, cancel, confirm a manual publish (Phase 07)."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from videocreator.db import get_conn, query_one, record_audit
from videocreator.state_posts import recompute_video_status_from_posts, transition_post
from videocreator.timeutil import utc_now_iso


def retry_failed_post(
    db_file: Path,
    post_id: int,
    *,
    scheduled_at_iso: str | None = None,
    now_dt: datetime | None = None,
    actor: str = "ui",
) -> bool:
    """Resets a `failed` or `missed` post back to `scheduled` (`attempts=0`, `next_attempt_at=NULL`)."""
    p_row = query_one(
        db_file, "SELECT id, video_id, status FROM posts WHERE id = ?", (post_id,)
    )
    if p_row is None:
        raise LookupError(f"Post #{post_id} not found")
    cur_status = str(p_row["status"])
    if cur_status not in ("failed", "missed"):
        return False

    new_sched = scheduled_at_iso or utc_now_iso(now_dt)
    video_id = int(p_row["video_id"])
    with get_conn(db_file) as conn:
        if not transition_post(conn, post_id, "scheduled", expected_from=cur_status):
            return False
        conn.execute(
            """
            UPDATE posts
            SET scheduled_at = ?,
                attempts = 0,
                next_attempt_at = NULL,
                error = NULL
            WHERE id = ?
            """,
            (new_sched, post_id),
        )
        recompute_video_status_from_posts(conn, video_id)
        record_audit(
            conn,
            actor=actor,
            action="post.retried",
            object_type="post",
            object_id=post_id,
            detail=f"from={cur_status}, at={new_sched}",
        )
    return True


def reschedule_post(
    db_file: Path,
    post_id: int,
    scheduled_at_iso: str,
    *,
    actor: str = "ui",
) -> bool:
    """Updates `scheduled_at` of an unposted (`scheduled` / `failed` / `missed`) post."""
    p_row = query_one(
        db_file, "SELECT id, video_id, status FROM posts WHERE id = ?", (post_id,)
    )
    if p_row is None:
        raise LookupError(f"Post #{post_id} not found")
    cur_status = str(p_row["status"])
    if cur_status not in ("scheduled", "failed", "missed"):
        return False

    video_id = int(p_row["video_id"])
    with get_conn(db_file) as conn:
        conn.execute(
            """
            UPDATE posts
            SET status = 'scheduled',
                scheduled_at = ?,
                attempts = 0,
                next_attempt_at = NULL,
                error = NULL
            WHERE id = ?
            """,
            (scheduled_at_iso, post_id),
        )
        recompute_video_status_from_posts(conn, video_id)
        record_audit(
            conn,
            actor=actor,
            action="post.rescheduled",
            object_type="post",
            object_id=post_id,
            detail=f"at={scheduled_at_iso}",
        )
    return True


def cancel_scheduled_post(
    db_file: Path,
    post_id: int,
    *,
    actor: str = "ui",
) -> bool:
    """Deletes an unposted `scheduled` / `missed` / `failed` post; if no posts remain for the video, returns video to `approved`."""
    p_row = query_one(
        db_file, "SELECT id, video_id, status FROM posts WHERE id = ?", (post_id,)
    )
    if p_row is None:
        raise LookupError(f"Post #{post_id} not found")
    if str(p_row["status"]) in ("publishing", "posted"):
        return False

    video_id = int(p_row["video_id"])
    with get_conn(db_file) as conn:
        conn.execute("DELETE FROM posts WHERE id = ?", (post_id,))
        rem = conn.execute(
            "SELECT COUNT(*) AS c FROM posts WHERE video_id = ?", (video_id,)
        ).fetchone()
        if rem is not None and int(rem["c"]) == 0:
            conn.execute(
                "UPDATE videos SET status = 'approved' WHERE id = ? AND status IN ('scheduled', 'failed')",
                (video_id,),
            )
        else:
            recompute_video_status_from_posts(conn, video_id)
        record_audit(
            conn,
            actor=actor,
            action="post.cancelled",
            object_type="post",
            object_id=post_id,
            detail=f"video_id={video_id}",
        )
    return True


def confirm_user_action_post(
    db_file: Path,
    post_id: int,
    *,
    external_post_id: str | None = None,
    permalink: str | None = None,
    actor: str = "ui",
) -> bool:
    """Marks a `needs_user_action` post (e.g. TikTok inbox) as `posted` after user confirmation."""
    p_row = query_one(
        db_file, "SELECT id, status FROM posts WHERE id = ?", (post_id,)
    )
    if p_row is None:
        raise LookupError(f"Post #{post_id} not found")
    if str(p_row["status"]) != "needs_user_action":
        return False
    won = transition_post(
        db_file,
        post_id,
        "posted",
        expected_from="needs_user_action",
        external_post_id=external_post_id,
        permalink=permalink,
    )
    if won:
        with get_conn(db_file) as conn:
            record_audit(
                conn,
                actor=actor,
                action="post.confirmed_posted",
                object_type="post",
                object_id=post_id,
                detail=permalink or external_post_id,
            )
    return won

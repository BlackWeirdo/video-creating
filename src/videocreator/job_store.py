"""Job rows in SQLite: claiming, completing, recovery after a restart, and quota waits."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from videocreator.db import get_conn

logger = logging.getLogger("videocreator.jobs")

# The owner's subscription-backed provider (no per-call cost); see `ai/claude_cli.py`.
SUBSCRIPTION_PROVIDER = "claude_cli"


# Minimum seconds between attempts of a waiting job while only other providers are resting.
WAKE_COOLDOWN_S = 300


def recover_interrupted_jobs(db_file: Path) -> int:
    """Resets any jobs stuck in 'running' back to 'queued' on startup,
    and resets posts stuck in 'publishing' without a remote_container_id back to 'scheduled'."""
    with get_conn(db_file) as conn:
        cur = conn.execute(
            """
            UPDATE jobs
            SET status = 'queued', started_at = NULL
            WHERE status = 'running'
            """
        )
        recovered_jobs = int(cur.rowcount or 0)
        conn.execute(
            """
            UPDATE posts
            SET status = 'scheduled'
            WHERE status = 'publishing' AND (remote_container_id IS NULL OR remote_container_id = '')
            """
        )
    if recovered_jobs:
        logger.info("Recovered %d interrupted running job(s) back to queued", recovered_jobs)
    return recovered_jobs


def requeue_waiting_quota_jobs(db_file: Path) -> int:
    with get_conn(db_file) as conn:
        cur = conn.execute(
            "UPDATE jobs SET status = 'queued' WHERE status = 'waiting_quota'"
        )
        return int(cur.rowcount or 0)


def wake_expired_quota_jobs(db_file: Path, *, cooldown_s: int = WAKE_COOLDOWN_S) -> int:
    """Requeues `waiting_quota` jobs once a provider they can use is available again.

    - No provider resting: wake every waiting job at once.
    - Only other providers resting (e.g. Gemini free tier) while the subscription provider
      `claude_cli` is free: wake jobs that have waited at least `cooldown_s` seconds since they
      entered the wait (`finished_at`), so a failing `claude_cli` call is retried at most once per cooldown
      instead of in a tight loop.
    - `claude_cli` itself resting: keep waiting.
    """
    with get_conn(db_file) as conn:
        resting = {
            str(r["name"])
            for r in conn.execute(
                "SELECT name FROM provider_state WHERE resting_until IS NOT NULL AND resting_until > unixepoch('now')"
            ).fetchall()
        }
        if not resting:
            cur = conn.execute(
                "UPDATE jobs SET status = 'queued' WHERE status = 'waiting_quota'"
            )
            return int(cur.rowcount or 0)
        if SUBSCRIPTION_PROVIDER in resting:
            return 0
        cur = conn.execute(
            """
            UPDATE jobs SET status = 'queued'
            WHERE status = 'waiting_quota'
              AND (COALESCE(finished_at, started_at) IS NULL
                   OR COALESCE(finished_at, started_at) <= strftime('%Y-%m-%dT%H:%M:%SZ', 'now', ?))
            """,
            (f"-{int(cooldown_s)} seconds",),
        )
        return int(cur.rowcount or 0)


def claim_next_queued_job(db_file: Path) -> dict[str, Any] | None:
    with get_conn(db_file) as conn:
        row = conn.execute(
            """
            SELECT id, kind, ref_id, status, created_at
            FROM jobs
            WHERE status = 'queued'
            ORDER BY id ASC
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            return None
        job_id = int(row["id"])
        cur = conn.execute(
            """
            UPDATE jobs
            SET status = 'running',
                started_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now'),
                finished_at = NULL,
                error = NULL
            WHERE id = ? AND status = 'queued'
            """,
            (job_id,),
        )
        if cur.rowcount != 1:
            return None
        return dict(row)


def complete_job(
    db_file: Path,
    job_id: int,
    *,
    status: str = "done",
    error: str | None = None,
    log_tail: str | None = None,
) -> None:
    if status not in ("done", "failed", "waiting_quota", "queued"):
        raise ValueError(f"Invalid job completion status: {status}")
    with get_conn(db_file) as conn:
        if status in ("done", "failed"):
            conn.execute(
                """
                UPDATE jobs
                SET status = ?,
                    error = ?,
                    log_tail = COALESCE(?, log_tail),
                    finished_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
                WHERE id = ?
                """,
                (status, error, log_tail, job_id),
            )
        elif status == "waiting_quota":
            # finished_at marks when the wait began; wake_expired_quota_jobs measures its cooldown from it.
            conn.execute(
                """
                UPDATE jobs
                SET status = ?,
                    error = ?,
                    log_tail = COALESCE(?, log_tail),
                    finished_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
                WHERE id = ?
                """,
                (status, error, log_tail, job_id),
            )
        else:
            conn.execute(
                """
                UPDATE jobs
                SET status = ?,
                    error = ?,
                    log_tail = COALESCE(?, log_tail)
                WHERE id = ?
                """,
                (status, error, log_tail, job_id),
            )

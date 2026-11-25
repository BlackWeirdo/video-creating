"""Job rows in SQLite: claiming, lane routing, progress, pause/resume, recovery, and quota waits."""
from __future__ import annotations

import contextvars
import logging
from pathlib import Path
from typing import Any

from videocreator.db import get_conn, get_setting, get_write_conn, query_all, set_setting

logger = logging.getLogger("videocreator.jobs")

_ACTIVE_JOB_CTX: contextvars.ContextVar[tuple[Path, int] | None] = contextvars.ContextVar(
    "videocreator_active_job", default=None
)


def bind_active_job_context(
    db_file: Path, job_id: int
) -> contextvars.Token[tuple[Path, int] | None]:
    return _ACTIVE_JOB_CTX.set((Path(db_file), int(job_id)))


def reset_active_job_context(
    token: contextvars.Token[tuple[Path, int] | None],
) -> None:
    _ACTIVE_JOB_CTX.reset(token)


def get_active_job_context() -> tuple[Path, int] | None:
    return _ACTIVE_JOB_CTX.get()

# The owner's subscription-backed provider (no per-call cost); see `ai/claude_cli.py`.
SUBSCRIPTION_PROVIDER = "claude_cli"

# Minimum seconds between attempts of a waiting job while only other providers are resting.
WAKE_COOLDOWN_S = 300

QUEUE_PAUSED_SETTING_KEY = "queue_paused"
MAX_JOB_ATTEMPTS = 3
CRASH_LOOP_FAILURE_MESSAGE = (
    "Tác vụ bị gián đoạn nhiều lần liên tiếp — có thể do thiếu RAM hoặc lỗi thư viện hệ thống."
)
VALID_LANES: tuple[str, ...] = ("io", "compute")
JOB_STATUSES: tuple[str, ...] = ("queued", "running", "waiting_quota", "done", "failed")


def is_queue_paused(db_file: Path) -> bool:
    return get_setting(db_file, QUEUE_PAUSED_SETTING_KEY, "0") == "1"


def set_queue_paused(db_file: Path, paused: bool) -> bool:
    set_setting(db_file, QUEUE_PAUSED_SETTING_KEY, "1" if paused else "0")
    return paused


def recover_interrupted_jobs(db_file: Path, *, max_attempts: int = MAX_JOB_ATTEMPTS) -> int:
    """Resets jobs stuck in 'running' back to 'queued' on startup unless they have already crashed
    `max_attempts` times (in which case they transition to 'failed' to break crash loops), and resets
    posts stuck in 'publishing' back to 'scheduled'."""
    cap = max(1, int(max_attempts))
    with get_write_conn(db_file) as conn:
        failed_cur = conn.execute(
            """
            UPDATE jobs
            SET status = 'failed',
                error = ?,
                finished_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
            WHERE status = 'running' AND COALESCE(attempts, 0) >= ?
            """,
            (CRASH_LOOP_FAILURE_MESSAGE, cap),
        )
        failed_jobs = int(failed_cur.rowcount or 0)
        cur = conn.execute(
            """
            UPDATE jobs
            SET status = 'queued', started_at = NULL
            WHERE status = 'running'
            """
        )
        recovered_jobs = int(cur.rowcount or 0)
        posts_cur = conn.execute(
            "UPDATE posts SET status = 'scheduled' WHERE status = 'publishing'"
        )
        recovered_posts = int(posts_cur.rowcount or 0)
    if failed_jobs:
        logger.warning(
            "Marked %d repeatedly interrupted job(s) as failed (attempts >= %d)",
            failed_jobs,
            cap,
        )
    if recovered_jobs:
        logger.info("Recovered %d interrupted running job(s) back to queued", recovered_jobs)
    if recovered_posts:
        logger.info(
            "Recovered %d interrupted publishing post(s) back to scheduled",
            recovered_posts,
        )
    return recovered_jobs


def retry_failed_job(db_file: Path, job_id: int) -> dict[str, Any]:
    """Manually resets a failed or waiting_quota job back to `queued` with `attempts = 0`."""
    with get_write_conn(db_file) as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (int(job_id),)).fetchone()
        if row is None:
            raise LookupError(f"Job {job_id} not found")
        if str(row["status"]) == "running":
            raise ValueError(f"Job {job_id} is currently running")
        conn.execute(
            """
            UPDATE jobs
            SET status = 'queued',
                attempts = 0,
                error = NULL,
                started_at = NULL,
                finished_at = NULL,
                progress = 0.0,
                step = ''
            WHERE id = ?
            """,
            (int(job_id),),
        )
        fresh = conn.execute("SELECT * FROM jobs WHERE id = ?", (int(job_id),)).fetchone()
        assert fresh is not None
        return dict(fresh)


def requeue_waiting_quota_jobs(db_file: Path) -> int:
    with get_write_conn(db_file) as conn:
        cur = conn.execute(
            "UPDATE jobs SET status = 'queued' WHERE status = 'waiting_quota'"
        )
        return int(cur.rowcount or 0)


def wake_expired_quota_jobs(db_file: Path, *, cooldown_s: int = WAKE_COOLDOWN_S) -> int:
    """Requeues `waiting_quota` jobs once a provider they can use is available again."""
    with get_write_conn(db_file) as conn:
        resting = {
            str(r["name"])
            for r in conn.execute(
                "SELECT name FROM provider_state WHERE resting_until IS NOT NULL AND CAST(resting_until AS INTEGER) > unixepoch('now')"
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


def claim_next_queued_job(
    db_file: Path, *, lane: str | None = None
) -> dict[str, Any] | None:
    if lane is not None and lane not in VALID_LANES:
        raise ValueError(f"Invalid job lane: {lane}")
    with get_write_conn(db_file) as conn:
        if lane is not None:
            row = conn.execute(
                """
                SELECT id, kind, ref_id, status, lane, workspace_id, progress, step, attempts, created_at
                FROM jobs
                WHERE status = 'queued' AND lane = ?
                ORDER BY priority DESC, id ASC
                LIMIT 1
                """,
                (lane,),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT id, kind, ref_id, status, lane, workspace_id, progress, step, attempts, created_at
                FROM jobs
                WHERE status = 'queued'
                ORDER BY priority DESC, id ASC
                LIMIT 1
                """
            ).fetchone()
        if row is None:
            return None
        job_id = int(row["id"])
        next_attempts = int(row["attempts"] or 0) + 1
        cur = conn.execute(
            """
            UPDATE jobs
            SET status = 'running',
                attempts = ?,
                started_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now'),
                finished_at = NULL,
                error = NULL
            WHERE id = ? AND status = 'queued'
            """,
            (next_attempts, job_id),
        )
        if cur.rowcount != 1:
            return None
        claimed = dict(row)
        claimed["status"] = "running"
        claimed["attempts"] = next_attempts
        return claimed


def update_job_progress(
    db_file: Path, job_id: int, *, progress: float, step: str = ""
) -> None:
    clamped = max(0.0, min(1.0, float(progress)))
    with get_conn(db_file) as conn:
        conn.execute(
            "UPDATE jobs SET progress = ?, step = ? WHERE id = ?",
            (clamped, step.strip()[:120], job_id),
        )


def report_active_job_progress(
    progress: float, step: str = "", *, db_file: Path | None = None
) -> bool:
    """Updates `(progress, step)` of the currently executing worker job if inside `run_one_job`."""
    ctx = _ACTIVE_JOB_CTX.get()
    if ctx is None:
        return False
    ctx_db, ctx_job_id = ctx
    if db_file is not None and Path(db_file).resolve() != ctx_db.resolve():
        return False
    try:
        update_job_progress(ctx_db, ctx_job_id, progress=progress, step=step)
        return True
    except Exception as exc:
        logger.debug("Ignored progress update error on job #%d: %s", ctx_job_id, exc)
        return False


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
        if status == "done":
            conn.execute(
                """
                UPDATE jobs
                SET status = ?,
                    error = ?,
                    log_tail = COALESCE(?, log_tail),
                    progress = 1.0,
                    step = CASE WHEN step = '' THEN 'Hoàn tất' ELSE step END,
                    finished_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
                WHERE id = ?
                """,
                (status, error, log_tail, job_id),
            )
        elif status in ("failed", "waiting_quota"):
            # For waiting_quota, finished_at marks when the wait began; wake_expired_quota_jobs measures cooldown from it.
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


def get_queue_summary(
    db_file: Path, *, workspace_id: int | None = None
) -> dict[str, Any]:
    by_status = {s: 0 for s in JOB_STATUSES}
    by_lane = {
        lane: {s: 0 for s in JOB_STATUSES} for lane in VALID_LANES
    }
    params: list[Any] = []
    where = ""
    if workspace_id is not None:
        where = "WHERE workspace_id = ?"
        params.append(int(workspace_id))
    rows = query_all(
        db_file,
        f"SELECT lane, status, COUNT(*) AS cnt FROM jobs {where} GROUP BY lane, status",
        params,
    )
    for row in rows:
        lane = str(row.get("lane") or "io")
        st = str(row.get("status") or "")
        cnt = int(row["cnt"])
        if st in by_status:
            by_status[st] += cnt
        if lane in by_lane and st in by_lane[lane]:
            by_lane[lane][st] += cnt
    return {
        "paused": is_queue_paused(db_file),
        "by_status": by_status,
        "by_lane": by_lane,
    }


def list_jobs(
    db_file: Path,
    *,
    workspace_id: int | None = None,
    status: str | None = None,
    lane: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if workspace_id is not None:
        clauses.append("workspace_id = ?")
        params.append(int(workspace_id))
    if status is not None:
        clauses.append("status = ?")
        params.append(status.strip())
    if lane is not None:
        if lane not in VALID_LANES:
            raise ValueError(f"Invalid job lane: {lane}")
        clauses.append("lane = ?")
        params.append(lane)
    sql = "SELECT * FROM jobs"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    clamped_limit = max(1, min(500, int(limit)))
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(clamped_limit)
    return query_all(db_file, sql, params)

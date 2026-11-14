"""SQLite-backed job queue and single-concurrency asyncio worker."""
from __future__ import annotations

import asyncio
import inspect
import logging
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any

from videocreator.db import get_conn

logger = logging.getLogger("videocreator.jobs")

JobHandler = Callable[[int | None], Any]

# The owner's subscription-backed provider (no per-call cost); see `ai/claude_cli.py`.
SUBSCRIPTION_PROVIDER = "claude_cli"
# Minimum seconds between attempts of a waiting job while only other providers are resting.
WAKE_COOLDOWN_S = 300


class QuotaWaitRequested(Exception):
    """Raised by a job handler when subscription quota is exhausted and policy is 'never' or 'ask'."""

    def __init__(self, reason: str = "Waiting for subscription quota", *, retry_after_s: int = 3600) -> None:
        super().__init__(reason)
        self.reason = reason
        self.retry_after_s = retry_after_s


class JobRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, JobHandler] = {}

    def register(self, kind: str, handler: JobHandler) -> None:
        self._handlers[kind] = handler

    def get(self, kind: str) -> JobHandler | None:
        return self._handlers.get(kind)

    def kinds(self) -> list[str]:
        return sorted(self._handlers.keys())


default_registry = JobRegistry()


def register_job_handler(kind: str, handler: JobHandler) -> None:
    default_registry.register(kind, handler)


def enqueue_job(db_file: Path, kind: str, ref_id: int | None = None) -> int:
    with get_conn(db_file) as conn:
        cur = conn.execute(
            "INSERT INTO jobs (kind, ref_id, status) VALUES (?, ?, 'queued')",
            (kind, ref_id),
        )
        return int(cur.lastrowid or 0)


def get_job(db_file: Path, job_id: int) -> dict[str, Any] | None:
    with get_conn(db_file) as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row is not None else None


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


async def run_one_job(
    db_file: Path,
    registry: JobRegistry = default_registry,
) -> bool:
    """Claims and executes the oldest queued job. Returns True if a job was processed."""
    job = claim_next_queued_job(db_file)
    if job is None:
        return False

    job_id = int(job["id"])
    kind = str(job["kind"])
    ref_id = int(job["ref_id"]) if job["ref_id"] is not None else None
    handler = registry.get(kind)
    if handler is None:
        msg = f"No handler registered for job kind '{kind}'"
        logger.error("Job %d failed: %s", job_id, msg)
        complete_job(db_file, job_id, status="failed", error=msg)
        return True

    logger.info("Starting job id=%d kind=%s ref_id=%s", job_id, kind, ref_id)
    try:
        if inspect.iscoroutinefunction(handler):
            result = await handler(ref_id)
        else:
            result = await asyncio.to_thread(handler, ref_id)
        log_tail = str(result)[:2000] if isinstance(result, str) else None
        complete_job(db_file, job_id, status="done", log_tail=log_tail)
        logger.info("Finished job id=%d kind=%s", job_id, kind)
    except QuotaWaitRequested as exc:
        logger.warning("Job id=%d waiting for quota: %s", job_id, exc)
        complete_job(db_file, job_id, status="waiting_quota", error=str(exc))
    except Exception as exc:
        tb_tail = "".join(traceback.format_exception(exc))[-2000:]
        logger.error("Job id=%d kind=%s failed: %s", job_id, kind, exc)
        complete_job(
            db_file,
            job_id,
            status="failed",
            error=str(exc)[:500],
            log_tail=tb_tail,
        )
    return True


class JobWorker:
    """Single-concurrency background asyncio worker polling the jobs table."""

    def __init__(
        self,
        db_file: Path,
        registry: JobRegistry = default_registry,
        poll_interval_s: float = 0.5,
    ) -> None:
        self.db_file = db_file
        self.registry = registry
        self.poll_interval_s = poll_interval_s
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        recover_interrupted_jobs(self.db_file)
        self._stop_event.clear()
        self._task = asyncio.create_task(self._loop(), name="videocreator-job-worker")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._task.cancel()
            self._task = None

    async def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                wake_expired_quota_jobs(self.db_file)
                processed = await run_one_job(self.db_file, self.registry)
                if processed:
                    continue
            except Exception as exc:
                logger.error("Unexpected worker loop error: %s", exc)
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=self.poll_interval_s
                )
            except asyncio.TimeoutError:
                pass

    def run_next_once(self) -> bool:
        """Synchronous convenience wrapper for executing a single job tick in tests."""
        return asyncio.run(run_one_job(self.db_file, self.registry))

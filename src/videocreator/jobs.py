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
from videocreator.job_store import (
    claim_next_queued_job,
    complete_job,
    recover_interrupted_jobs,
    wake_expired_quota_jobs,
)

logger = logging.getLogger("videocreator.jobs")

JobHandler = Callable[[int | None], Any]


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


PRIORITY_USER = 10  # someone is waiting for the result
PRIORITY_PINNED = 5  # a trend video the owner pasted by hand
PRIORITY_BACKGROUND = 0
USER_FACING_KINDS = frozenset({"plan", "render", "replan", "studio"})


def enqueue_job(
    db_file: Path, kind: str, ref_id: int | None = None, *, priority: int | None = None
) -> int:
    """Queues a job. The worker takes higher `priority` first, then the oldest; user-facing kinds
    default to `PRIORITY_USER` so they never wait behind a batch of background analyses."""
    prio = priority if priority is not None else (
        PRIORITY_USER if kind in USER_FACING_KINDS else PRIORITY_BACKGROUND
    )
    with get_conn(db_file) as conn:
        cur = conn.execute(
            "INSERT INTO jobs (kind, ref_id, status, priority) VALUES (?, ?, 'queued', ?)",
            (kind, ref_id, prio),
        )
        return int(cur.lastrowid or 0)


def get_job(db_file: Path, job_id: int) -> dict[str, Any] | None:
    with get_conn(db_file) as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row is not None else None


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

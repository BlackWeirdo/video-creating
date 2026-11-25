"""SQLite-backed dual-lane job queue and asyncio worker."""
from __future__ import annotations

import asyncio
import gc
import inspect
import logging
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any

from videocreator.db import get_conn
from videocreator.job_store import (
    VALID_LANES,
    bind_active_job_context,
    claim_next_queued_job,
    complete_job,
    is_queue_paused,
    recover_interrupted_jobs,
    reset_active_job_context,
    set_queue_paused,
    update_job_progress,
    wake_expired_quota_jobs,
)
from videocreator.workspaces import DEFAULT_WORKSPACE_ID, require_workspace

logger = logging.getLogger("videocreator.jobs")

JobHandler = Callable[[int | None], Any]

COMPUTE_JOB_KINDS: frozenset[str] = frozenset(
    {
        "render",
        "restyle_video",
        "analyse",
        "studio",
        "localize_extract",
        "localize_render",
        "news_render",
        "novel_render",
        "podcast_render",
        "lipsync_render",
        "editor_render",
        "workflow_run",
        "muse_storyboard_assemble",
        "audio_separate",
        "whisper_asr",
        "inpaint_subtitles",
    }
)


def classify_job_lane(kind: str) -> str:
    return "compute" if kind in COMPUTE_JOB_KINDS else "io"


class QuotaWaitRequested(Exception):
    """Raised by a job handler when subscription quota is exhausted and policy is 'never' or 'ask'."""

    def __init__(
        self, reason: str = "Waiting for subscription quota", *, retry_after_s: int = 3600
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        self.retry_after_s = retry_after_s


class JobRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, JobHandler] = {}
        self._lanes: dict[str, str] = {}

    def register(
        self, kind: str, handler: JobHandler, *, lane: str | None = None
    ) -> None:
        chosen_lane = lane if lane is not None else classify_job_lane(kind)
        if chosen_lane not in VALID_LANES:
            raise ValueError(f"Invalid job lane: {chosen_lane}")
        self._handlers[kind] = handler
        self._lanes[kind] = chosen_lane

    def get(self, kind: str) -> JobHandler | None:
        return self._handlers.get(kind)

    def get_lane(self, kind: str) -> str:
        return self._lanes.get(kind) or classify_job_lane(kind)

    def kinds(self) -> list[str]:
        return sorted(self._handlers.keys())


default_registry = JobRegistry()


PRIORITY_USER = 10  # someone is waiting for the result
PRIORITY_PINNED = 5  # a trend video the owner pasted by hand
PRIORITY_BACKGROUND = 0
# `analyse`/`describe` are footage the owner has just imported, so they also jump the trend batch.
USER_FACING_KINDS = frozenset(
    {
        "plan",
        "render",
        "replan",
        "restyle_video",
        "studio",
        "analyse",
        "describe",
        "localize_extract",
        "localize_render",
        "news_render",
        "novel_render",
        "podcast_render",
        "lipsync_render",
        "editor_render",
        "workflow_run",
        "muse_storyboard_assemble",
        "batch_run",
    }
)


def enqueue_job(
    db_file: Path,
    kind: str,
    ref_id: int | None = None,
    *,
    priority: int | None = None,
    lane: str | None = None,
    workspace_id: int = DEFAULT_WORKSPACE_ID,
    registry: JobRegistry = default_registry,
) -> int:
    """Queues a job with priority and execution lane (`io` or `compute`)."""
    require_workspace(db_file, workspace_id)
    chosen_lane = lane if lane is not None else registry.get_lane(kind)
    if chosen_lane not in VALID_LANES:
        raise ValueError(f"Invalid job lane: {chosen_lane}")
    prio = (
        priority
        if priority is not None
        else (PRIORITY_USER if kind in USER_FACING_KINDS else PRIORITY_BACKGROUND)
    )
    with get_conn(db_file) as conn:
        cur = conn.execute(
            """
            INSERT INTO jobs (kind, ref_id, status, priority, lane, workspace_id)
            VALUES (?, ?, 'queued', ?, ?, ?)
            """,
            (kind, ref_id, prio, chosen_lane, int(workspace_id)),
        )
        return int(cur.lastrowid or 0)


def get_job(db_file: Path, job_id: int) -> dict[str, Any] | None:
    with get_conn(db_file) as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row is not None else None


async def run_one_job(
    db_file: Path,
    registry: JobRegistry = default_registry,
    *,
    lane: str | None = None,
) -> bool:
    """Claims and executes the next queued job (optionally filtered by lane)."""
    job = claim_next_queued_job(db_file, lane=lane)
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

    logger.info(
        "Starting job id=%d kind=%s lane=%s ref_id=%s",
        job_id,
        kind,
        job.get("lane", "io"),
        ref_id,
    )
    token = bind_active_job_context(db_file, job_id)
    try:
        if float(job.get("progress") or 0.0) <= 0.0 and not str(job.get("step") or "").strip():
            update_job_progress(db_file, job_id, progress=0.05, step=f"Đang khởi chạy {kind}...")
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
    finally:
        reset_active_job_context(token)
        if job.get("lane") == "compute":
            gc.collect()
    return True


class JobWorker:
    """Dual-lane background asyncio worker polling the jobs table (`io` + `compute`)."""

    def __init__(
        self,
        db_file: Path,
        registry: JobRegistry = default_registry,
        poll_interval_s: float = 0.5,
        *,
        io_concurrency: int = 4,
        compute_concurrency: int = 1,
    ) -> None:
        if io_concurrency < 1 or compute_concurrency < 1:
            raise ValueError("Worker lane concurrency must be >= 1")
        self.db_file = db_file
        self.registry = registry
        self.poll_interval_s = poll_interval_s
        self.io_concurrency = int(io_concurrency)
        self.compute_concurrency = int(compute_concurrency)
        self._stop_event = asyncio.Event()
        self._tasks: list[asyncio.Task[None]] = []
        self._active_executions = 0

    @property
    def active_executions(self) -> int:
        return self._active_executions

    async def wait_until_idle(self, timeout_s: float = 10.0) -> bool:
        """Waits until no in-flight job handler is actively executing in this worker."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max(0.1, timeout_s)
        while self._active_executions > 0:
            if loop.time() >= deadline:
                return False
            await asyncio.sleep(0.05)
        return True

    @property
    def is_paused(self) -> bool:
        return is_queue_paused(self.db_file)

    def pause(self) -> None:
        set_queue_paused(self.db_file, True)

    def resume(self) -> None:
        set_queue_paused(self.db_file, False)

    def start(self) -> None:
        if any(not t.done() for t in self._tasks):
            return
        recover_interrupted_jobs(self.db_file)
        self._stop_event.clear()
        self._tasks = []
        for idx in range(self.io_concurrency):
            self._tasks.append(
                asyncio.create_task(
                    self._lane_loop("io", wake_quota=(idx == 0)),
                    name=f"videocreator-job-io-{idx}",
                )
            )
        for idx in range(self.compute_concurrency):
            self._tasks.append(
                asyncio.create_task(
                    self._lane_loop("compute", wake_quota=False),
                    name=f"videocreator-job-compute-{idx}",
                )
            )

    async def stop(self) -> None:
        self._stop_event.set()
        if not self._tasks:
            return
        try:
            await asyncio.wait_for(
                asyncio.gather(*self._tasks, return_exceptions=True), timeout=5.0
            )
        except asyncio.TimeoutError:
            for task in self._tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []

    async def _lane_loop(self, lane: str, *, wake_quota: bool = False) -> None:
        while not self._stop_event.is_set():
            try:
                if wake_quota:
                    wake_expired_quota_jobs(self.db_file)
                if not self.is_paused:
                    self._active_executions += 1
                    try:
                        processed = await run_one_job(
                            self.db_file, self.registry, lane=lane
                        )
                    finally:
                        self._active_executions = max(0, self._active_executions - 1)
                    if processed:
                        continue
            except Exception as exc:
                logger.error("Unexpected worker loop error (lane=%s): %s", lane, exc, exc_info=True)
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=self.poll_interval_s
                )
            except asyncio.TimeoutError:
                pass

    def run_next_once(self, *, lane: str | None = None) -> bool:
        """Synchronous convenience wrapper for executing a single job tick in tests."""
        return asyncio.run(run_one_job(self.db_file, self.registry, lane=lane))

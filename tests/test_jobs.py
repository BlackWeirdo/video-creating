"""Real SQLite job queue, worker execution, and crash recovery tests (no mocks)."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from videocreator.ai.quota import mark_provider_resting
from videocreator.db import execute, migrate, query_one
from videocreator.job_store import (
    claim_next_queued_job,
    recover_interrupted_jobs,
    requeue_waiting_quota_jobs,
    wake_expired_quota_jobs,
)
from videocreator.jobs import JobRegistry, JobWorker, QuotaWaitRequested, enqueue_job, run_one_job

pytestmark = pytest.mark.local


def test_job_worker_executes_and_recovers_after_crash(tmp_path: Path) -> None:
    db_file = tmp_path / "app.db"
    migrate(db_file)

    # Insert a job stuck in 'running' as if the process crashed mid-execution
    crashed_job_id = execute(
        db_file,
        "INSERT INTO jobs (kind, ref_id, status, started_at) VALUES ('sample_work', 42, 'running', '2026-11-13T01:00:00Z')",
    )
    second_job_id = enqueue_job(db_file, "sample_work", ref_id=99)

    processed_refs: list[int | None] = []
    registry = JobRegistry()

    def _handler(ref_id: int | None) -> str:
        processed_refs.append(ref_id)
        return f"completed ref={ref_id}"

    registry.register("sample_work", _handler)

    async def _run() -> None:
        recovered = recover_interrupted_jobs(db_file)
        assert recovered == 1

        worker = JobWorker(db_file, registry=registry, poll_interval_s=0.05)
        worker.start()
        try:
            for _ in range(40):
                row1 = query_one(db_file, "SELECT status FROM jobs WHERE id = ?", (crashed_job_id,))
                row2 = query_one(db_file, "SELECT status FROM jobs WHERE id = ?", (second_job_id,))
                if row1 and row2 and row1["status"] == "done" and row2["status"] == "done":
                    break
                await asyncio.sleep(0.05)
        finally:
            await worker.stop()

    asyncio.run(_run())

    assert processed_refs == [42, 99]
    j1 = query_one(db_file, "SELECT status, log_tail, finished_at FROM jobs WHERE id = ?", (crashed_job_id,))
    j2 = query_one(db_file, "SELECT status, log_tail, finished_at FROM jobs WHERE id = ?", (second_job_id,))
    assert j1 is not None and j1["status"] == "done" and j1["finished_at"] is not None
    assert j2 is not None and j2["status"] == "done" and "completed ref=99" in str(j2["log_tail"])


def test_job_waiting_quota_and_failure_states(tmp_path: Path) -> None:
    db_file = tmp_path / "app.db"
    migrate(db_file)

    registry = JobRegistry()
    attempts = 0

    def _quota_handler(ref_id: int | None) -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise QuotaWaitRequested("claude_cli resting until 12:00Z")
        return "ok after quota reset"

    registry.register("ai_plan", _quota_handler)
    job_id = enqueue_job(db_file, "ai_plan", ref_id=7)

    asyncio.run(run_one_job(db_file, registry=registry))
    row = query_one(db_file, "SELECT status, error FROM jobs WHERE id = ?", (job_id,))
    assert row is not None
    assert row["status"] == "waiting_quota"
    assert "claude_cli" in str(row["error"])

    # When quota resets, waiting_quota jobs are requeued and succeed
    requeued = requeue_waiting_quota_jobs(db_file)
    assert requeued == 1
    asyncio.run(run_one_job(db_file, registry=registry))

    row_after = query_one(db_file, "SELECT status, log_tail FROM jobs WHERE id = ?", (job_id,))
    assert row_after is not None
    assert row_after["status"] == "done"
    assert row_after["log_tail"] == "ok after quota reset"


def _add_waiting_job(db_file: Path, started_ago_s: int) -> int:
    execute(
        db_file,
        """
        INSERT INTO jobs (kind, ref_id, status, started_at)
        VALUES ('plan', 1, 'waiting_quota', strftime('%Y-%m-%dT%H:%M:%SZ', 'now', ?))
        """,
        (f"-{started_ago_s} seconds",),
    )
    row = query_one(db_file, "SELECT MAX(id) AS id FROM jobs")
    assert row is not None
    return int(row["id"])


def test_wake_does_not_wait_for_gemini_when_claude_cli_is_free(tmp_path: Path) -> None:
    db_file = tmp_path / "app.db"
    migrate(db_file)
    mark_provider_resting(db_file, "gemini_api", duration_s=1800, error_msg="429 free tier")

    fresh_id = _add_waiting_job(db_file, started_ago_s=30)
    old_id = _add_waiting_job(db_file, started_ago_s=600)

    # Gemini rests, claude_cli does not: only the job past the cooldown is woken.
    assert wake_expired_quota_jobs(db_file, cooldown_s=300) == 1
    old = query_one(db_file, "SELECT status FROM jobs WHERE id = ?", (old_id,))
    fresh = query_one(db_file, "SELECT status FROM jobs WHERE id = ?", (fresh_id,))
    assert old is not None and old["status"] == "queued"
    assert fresh is not None and fresh["status"] == "waiting_quota"


def test_wake_keeps_waiting_while_claude_cli_is_resting(tmp_path: Path) -> None:
    db_file = tmp_path / "app.db"
    migrate(db_file)
    mark_provider_resting(db_file, "claude_cli", duration_s=1800, error_msg="session limit")
    job_id = _add_waiting_job(db_file, started_ago_s=3600)

    assert wake_expired_quota_jobs(db_file) == 0
    row = query_one(db_file, "SELECT status FROM jobs WHERE id = ?", (job_id,))
    assert row is not None and row["status"] == "waiting_quota"


def test_wake_everything_when_no_provider_is_resting(tmp_path: Path) -> None:
    db_file = tmp_path / "app.db"
    migrate(db_file)
    _add_waiting_job(db_file, started_ago_s=1)
    _add_waiting_job(db_file, started_ago_s=1)

    assert wake_expired_quota_jobs(db_file) == 2


def test_cooldown_counts_from_entering_the_wait_not_from_start(tmp_path: Path) -> None:
    """A job that ran long (started 1 h ago) and only just began waiting must not be woken at once."""
    db_file = tmp_path / "app.db"
    migrate(db_file)
    mark_provider_resting(db_file, "gemini_api", duration_s=1800, error_msg="429 free tier")
    job_id = _add_waiting_job(db_file, started_ago_s=3600)
    execute(
        db_file,
        "UPDATE jobs SET finished_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now', '-10 seconds') WHERE id = ?",
        (job_id,),
    )
    assert wake_expired_quota_jobs(db_file, cooldown_s=300) == 0

    execute(
        db_file,
        "UPDATE jobs SET finished_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now', '-400 seconds') WHERE id = ?",
        (job_id,),
    )
    assert wake_expired_quota_jobs(db_file, cooldown_s=300) == 1


def test_waiting_quota_stamps_wait_start_and_claim_clears_it(tmp_path: Path) -> None:
    db_file = tmp_path / "app.db"
    migrate(db_file)
    registry = JobRegistry()

    def _handler(_ref_id: int | None) -> str:
        raise QuotaWaitRequested("gemini_api resting")

    registry.register("ai_plan", _handler)
    job_id = enqueue_job(db_file, "ai_plan")
    asyncio.run(run_one_job(db_file, registry=registry))
    row = query_one(db_file, "SELECT status, finished_at FROM jobs WHERE id = ?", (job_id,))
    assert row is not None and row["status"] == "waiting_quota" and row["finished_at"] is not None

    requeue_waiting_quota_jobs(db_file)
    claimed = claim_next_queued_job(db_file)
    assert claimed is not None and int(claimed["id"]) == job_id
    mid = query_one(db_file, "SELECT finished_at FROM jobs WHERE id = ?", (job_id,))
    assert mid is not None and mid["finished_at"] is None

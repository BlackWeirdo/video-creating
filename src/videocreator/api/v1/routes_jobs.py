"""Dual-lane job listing and global queue pause/resume endpoints for `/api/v1`."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from videocreator.api.v1.routes_system import clear_nav_counts_cache
from videocreator.db import get_conn, record_audit
from videocreator.job_store import get_queue_summary, list_jobs, retry_failed_job, set_queue_paused
from videocreator.jobs import JobWorker, get_job
from videocreator.paths import AppPaths

router = APIRouter()


@router.get("/jobs")
async def api_list_jobs(
    request: Request,
    workspace_id: int | None = Query(default=None),
    status: str | None = Query(default=None),
    lane: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    try:
        items = list_jobs(
            paths.db_file,
            workspace_id=workspace_id,
            status=status,
            lane=lane,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(
        {
            "jobs": items,
            "queue": get_queue_summary(paths.db_file, workspace_id=workspace_id),
        }
    )


@router.get("/jobs/{job_id}")
async def api_get_job(request: Request, job_id: int) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    job = get_job(paths.db_file, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return JSONResponse({"job": job})


@router.post("/jobs/{job_id}/retry")
async def api_retry_job(request: Request, job_id: int) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    try:
        job = retry_failed_job(paths.db_file, job_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    with get_conn(paths.db_file) as conn:
        record_audit(
            conn,
            actor="api",
            action="job.retried",
            object_type="job",
            object_id=job_id,
            detail=str(job.get("kind") or ""),
        )
    clear_nav_counts_cache()
    return JSONResponse({"job": job})


@router.get("/queue/status")
async def api_queue_status(
    request: Request,
    workspace_id: int | None = Query(default=None),
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    return JSONResponse(get_queue_summary(paths.db_file, workspace_id=workspace_id))


@router.post("/queue/pause")
async def api_queue_pause(request: Request) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    worker: JobWorker | None = getattr(request.app.state, "worker", None)
    if worker is not None:
        worker.pause()
    else:
        set_queue_paused(paths.db_file, True)
    with get_conn(paths.db_file) as conn:
        record_audit(
            conn,
            actor="api",
            action="queue.paused",
            object_type="queue",
            detail="paused",
        )
    return JSONResponse(get_queue_summary(paths.db_file))


@router.post("/queue/resume")
async def api_queue_resume(request: Request) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    worker: JobWorker | None = getattr(request.app.state, "worker", None)
    if worker is not None:
        worker.resume()
    else:
        set_queue_paused(paths.db_file, False)
    with get_conn(paths.db_file) as conn:
        record_audit(
            conn,
            actor="api",
            action="queue.resumed",
            object_type="queue",
            detail="resumed",
        )
    return JSONResponse(get_queue_summary(paths.db_file))

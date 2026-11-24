"""Batch & Product A/B Studio endpoints for `/api/v1`."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from videocreator.api.v1.deps import resolve_workspace_id
from videocreator.jobs import enqueue_job
from videocreator.paths import AppPaths
from videocreator.pipeline.batch_studio import (
    create_batch_run,
    get_batch_run,
    list_batch_runs,
    run_batch_run,
)

router = APIRouter()


class BatchCreateBody(BaseModel):
    workspace_id: int | None = None
    title: str
    source_kind: str = "products"
    items: list[Any] = Field(default_factory=list)
    ab_count: int = 2
    style_presets: list[str] = Field(default_factory=list)
    aspect_ratio: str = "9:16"
    target_lang: str = "vi"
    target_accounts: list[int] = Field(default_factory=list)
    sync: bool = False


class BatchRetryBody(BaseModel):
    failed_only: bool = True
    sync: bool = False


@router.get("/batches")
async def api_v1_list_batches(
    request: Request,
    workspace_id: int | None = Query(default=None),
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    ws_id = resolve_workspace_id(paths.db_file, workspace_id)
    return JSONResponse(
        {
            "batches": list_batch_runs(paths.db_file, workspace_id=ws_id),
            "workspace_id": ws_id,
        }
    )


@router.post("/batches", status_code=201)
async def api_v1_create_batch(
    request: Request, body: BatchCreateBody
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    ws_id = resolve_workspace_id(paths.db_file, body.workspace_id)
    try:
        batch = create_batch_run(
            paths,
            workspace_id=ws_id,
            title=body.title,
            source_kind=body.source_kind,
            items=body.items,
            ab_count=body.ab_count,
            style_presets=body.style_presets or None,
            aspect_ratio=body.aspect_ratio,
            target_lang=body.target_lang,
            target_accounts=body.target_accounts,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    job_id: int | None = None
    if body.sync:
        batch = run_batch_run(paths, int(batch["id"]))
    else:
        job_id = enqueue_job(
            paths.db_file,
            "batch_run",
            ref_id=int(batch["id"]),
            lane="io",
            workspace_id=ws_id,
        )
    return JSONResponse({"batch": batch, "job_id": job_id}, status_code=201)


@router.get("/batches/{batch_id}")
async def api_v1_get_batch(request: Request, batch_id: int) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    batch = get_batch_run(paths.db_file, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail=f"Batch #{batch_id} not found")
    return JSONResponse({"batch": batch})


@router.post("/batches/{batch_id}/retry")
async def api_v1_retry_batch(
    request: Request,
    batch_id: int,
    body: BatchRetryBody | None = None,
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    batch = get_batch_run(paths.db_file, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail=f"Batch #{batch_id} not found")
    payload = body or BatchRetryBody()
    if payload.sync:
        updated = run_batch_run(paths, batch_id, failed_only=payload.failed_only)
        return JSONResponse({"batch": updated, "job_id": None})

    job_id = enqueue_job(
        paths.db_file,
        "batch_run",
        ref_id=batch_id,
        lane="io",
        workspace_id=int(batch["workspace_id"]),
    )
    return JSONResponse({"batch": batch, "job_id": job_id}, status_code=202)

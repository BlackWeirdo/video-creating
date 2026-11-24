"""Visual Workflow Node DAG endpoints for `/api/v1`."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from videocreator.api.v1.deps import resolve_workspace_id
from videocreator.jobs import enqueue_job
from videocreator.paths import AppPaths
from videocreator.pipeline.workflow_engine import (
    create_workflow,
    delete_workflow,
    execute_workflow,
    export_workflow_json,
    get_workflow,
    import_workflow_json,
    list_workflows,
    update_workflow,
)

router = APIRouter()


class WorkflowCreateBody(BaseModel):
    workspace_id: int | None = None
    name: str
    description: str = ""
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)
    is_template: bool = False


class WorkflowPatchBody(BaseModel):
    name: str | None = None
    description: str | None = None
    nodes: list[dict[str, Any]] | None = None
    edges: list[dict[str, Any]] | None = None


class WorkflowImportBody(BaseModel):
    workspace_id: int | None = None
    payload: dict[str, Any]


class WorkflowRunBody(BaseModel):
    workspace_id: int | None = None
    sync: bool = False


@router.get("/workflows")
async def api_v1_list_workflows(
    request: Request,
    workspace_id: int | None = Query(default=None),
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    ws_id = resolve_workspace_id(paths.db_file, workspace_id)
    return JSONResponse(
        {"workflows": list_workflows(paths.db_file, workspace_id=ws_id), "workspace_id": ws_id}
    )


@router.post("/workflows", status_code=201)
async def api_v1_create_workflow(
    request: Request, body: WorkflowCreateBody
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    ws_id = resolve_workspace_id(paths.db_file, body.workspace_id)
    try:
        wf = create_workflow(
            paths,
            workspace_id=ws_id,
            name=body.name,
            description=body.description,
            nodes=body.nodes,
            edges=body.edges,
            is_template=body.is_template,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse({"workflow": wf}, status_code=201)


@router.post("/workflows/import", status_code=201)
async def api_v1_import_workflow(
    request: Request, body: WorkflowImportBody
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    ws_id = resolve_workspace_id(paths.db_file, body.workspace_id)
    try:
        wf = import_workflow_json(paths, ws_id, body.payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse({"workflow": wf}, status_code=201)


@router.get("/workflows/{workflow_id}")
async def api_v1_get_workflow(request: Request, workflow_id: int) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    wf = get_workflow(paths.db_file, workflow_id)
    if wf is None:
        raise HTTPException(status_code=404, detail=f"Workflow #{workflow_id} not found")
    return JSONResponse({"workflow": wf})


@router.patch("/workflows/{workflow_id}")
async def api_v1_patch_workflow(
    request: Request, workflow_id: int, body: WorkflowPatchBody
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    try:
        wf = update_workflow(
            paths,
            workflow_id,
            name=body.name,
            description=body.description,
            nodes=body.nodes,
            edges=body.edges,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if wf is None:
        raise HTTPException(status_code=404, detail=f"Workflow #{workflow_id} not found")
    return JSONResponse({"workflow": wf})


@router.delete("/workflows/{workflow_id}")
async def api_v1_delete_workflow(request: Request, workflow_id: int) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    if not delete_workflow(paths, workflow_id):
        raise HTTPException(status_code=404, detail=f"Workflow #{workflow_id} not found")
    return JSONResponse({"ok": True, "deleted_id": workflow_id})


@router.get("/workflows/{workflow_id}/export")
async def api_v1_export_workflow(request: Request, workflow_id: int) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    try:
        exported = export_workflow_json(paths.db_file, workflow_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return JSONResponse(exported)


@router.post("/workflows/{workflow_id}/run")
async def api_v1_run_workflow(
    request: Request,
    workflow_id: int,
    body: WorkflowRunBody | None = None,
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    wf = get_workflow(paths.db_file, workflow_id)
    if wf is None:
        raise HTTPException(status_code=404, detail=f"Workflow #{workflow_id} not found")
    payload = body or WorkflowRunBody()
    ws_id = resolve_workspace_id(
        paths.db_file, payload.workspace_id if payload.workspace_id is not None else int(wf["workspace_id"])
    )
    if payload.sync:
        try:
            run_res = execute_workflow(paths, workflow_id, workspace_id_override=ws_id)
            return JSONResponse({"run": run_res, "job_id": None})
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    job_id = enqueue_job(
        paths.db_file,
        "workflow_run",
        ref_id=workflow_id,
        lane="compute",
        workspace_id=ws_id,
    )
    return JSONResponse({"run": None, "job_id": job_id}, status_code=202)

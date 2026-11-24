"""Workspace CRUD and active-workspace switching endpoints for `/api/v1`."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from videocreator.paths import AppPaths
from videocreator.workspaces import (
    archive_workspace,
    create_workspace,
    get_active_workspace_id,
    get_workspace,
    list_workspaces,
    set_active_workspace_id,
    update_workspace,
)

router = APIRouter()


class WorkspaceCreateBody(BaseModel):
    name: str
    slug: str = ""
    niche: str = "general"
    content_policy: str = "strict_footage"
    approval_mode: str = "single"
    default_aspect_ratio: str = "9:16"
    style_preset: str = "tiktok_karaoke"
    tg_chat_id: str = ""
    tg_bot_secret_key: str = ""
    settings: dict[str, Any] = Field(default_factory=dict)


class WorkspaceUpdateBody(BaseModel):
    name: str | None = None
    niche: str | None = None
    content_policy: str | None = None
    approval_mode: str | None = None
    default_aspect_ratio: str | None = None
    style_preset: str | None = None
    tg_chat_id: str | None = None
    tg_bot_secret_key: str | None = None
    settings: dict[str, Any] | None = None


@router.get("/workspaces")
async def api_list_workspaces(
    request: Request,
    include_archived: bool = Query(default=False),
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    items = list_workspaces(paths.db_file, include_archived=include_archived)
    return JSONResponse(
        {
            "workspaces": items,
            "active_workspace_id": get_active_workspace_id(paths.db_file),
        }
    )


@router.post("/workspaces", status_code=201)
async def api_create_workspace(
    request: Request, body: WorkspaceCreateBody
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    try:
        new_id = create_workspace(
            paths.db_file,
            name=body.name,
            slug=body.slug,
            niche=body.niche,
            content_policy=body.content_policy,
            approval_mode=body.approval_mode,
            default_aspect_ratio=body.default_aspect_ratio,
            style_preset=body.style_preset,
            tg_chat_id=body.tg_chat_id,
            tg_bot_secret_key=body.tg_bot_secret_key,
            settings=body.settings,
            actor="api",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    ws = get_workspace(paths.db_file, new_id)
    assert ws is not None
    return JSONResponse({"workspace": ws}, status_code=201)


@router.get("/workspaces/{workspace_id}")
async def api_get_workspace(request: Request, workspace_id: int) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    ws = get_workspace(paths.db_file, workspace_id)
    if ws is None:
        raise HTTPException(status_code=404, detail=f"Workspace {workspace_id} not found")
    return JSONResponse({"workspace": ws})


@router.patch("/workspaces/{workspace_id}")
async def api_update_workspace(
    request: Request, workspace_id: int, body: WorkspaceUpdateBody
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    try:
        ws = update_workspace(
            paths.db_file,
            workspace_id,
            name=body.name,
            niche=body.niche,
            content_policy=body.content_policy,
            approval_mode=body.approval_mode,
            default_aspect_ratio=body.default_aspect_ratio,
            style_preset=body.style_preset,
            tg_chat_id=body.tg_chat_id,
            tg_bot_secret_key=body.tg_bot_secret_key,
            settings=body.settings,
            actor="api",
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse({"workspace": ws})


@router.post("/workspaces/{workspace_id}/activate")
async def api_activate_workspace(request: Request, workspace_id: int) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    try:
        active_id = set_active_workspace_id(paths.db_file, workspace_id, actor="api")
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    ws = get_workspace(paths.db_file, active_id)
    return JSONResponse({"active_workspace_id": active_id, "workspace": ws})


@router.delete("/workspaces/{workspace_id}")
async def api_archive_workspace(request: Request, workspace_id: int) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    try:
        ws = archive_workspace(paths.db_file, workspace_id, actor="api")
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(
        {
            "workspace": ws,
            "active_workspace_id": get_active_workspace_id(paths.db_file),
        }
    )

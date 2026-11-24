"""Workspace Multi-Track Timeline Editor & Media Library endpoints for `/api/v1`."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from videocreator.api.v1.deps import resolve_workspace_id
from videocreator.editor_bridge import find_freecut_dist_dir
from videocreator.paths import AppPaths
from videocreator.pipeline.editor import (
    create_editor_project,
    get_editor_project,
    list_editor_media,
    list_editor_projects,
    render_editor_project,
    update_editor_project,
)

router = APIRouter()


class EditorCreateBody(BaseModel):
    workspace_id: int | None = None
    title: str = "Timeline Project"
    source_video_id: int | None = None
    aspect_ratio: str = "9:16"
    fps: int = 30
    tracks: dict[str, Any] | None = None


class EditorPatchBody(BaseModel):
    title: str | None = None
    aspect_ratio: str | None = None
    tracks: dict[str, Any] | None = None


class EditorRenderBody(BaseModel):
    style_preset: str = "tiktok_karaoke"


@router.get("/editor/media")
async def api_v1_editor_media(
    request: Request,
    workspace_id: int | None = Query(default=None),
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    ws_id = resolve_workspace_id(paths.db_file, workspace_id)
    media = list_editor_media(paths.db_file, workspace_id=ws_id)
    media["freecut_available"] = find_freecut_dist_dir() is not None
    return JSONResponse(media)


@router.get("/editor/projects")
async def api_v1_list_editor_projects(
    request: Request,
    workspace_id: int | None = Query(default=None),
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    ws_id = resolve_workspace_id(paths.db_file, workspace_id)
    return JSONResponse(
        {"projects": list_editor_projects(paths.db_file, workspace_id=ws_id), "workspace_id": ws_id}
    )


@router.post("/editor/projects", status_code=201)
async def api_v1_create_editor_project(
    request: Request, body: EditorCreateBody
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    ws_id = resolve_workspace_id(paths.db_file, body.workspace_id)
    proj = create_editor_project(
        paths,
        workspace_id=ws_id,
        title=body.title,
        source_video_id=body.source_video_id,
        aspect_ratio=body.aspect_ratio,
        fps=body.fps,
        tracks=body.tracks,
    )
    return JSONResponse({"project": proj}, status_code=201)


@router.get("/editor/projects/{project_id}")
async def api_v1_get_editor_project(request: Request, project_id: int) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    proj = get_editor_project(paths.db_file, project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail=f"Editor project #{project_id} not found")
    return JSONResponse({"project": proj})


@router.patch("/editor/projects/{project_id}")
async def api_v1_patch_editor_project(
    request: Request, project_id: int, body: EditorPatchBody
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    proj = update_editor_project(
        paths,
        project_id,
        title=body.title,
        aspect_ratio=body.aspect_ratio,
        tracks=body.tracks,
    )
    if proj is None:
        raise HTTPException(status_code=404, detail=f"Editor project #{project_id} not found")
    return JSONResponse({"project": proj})


@router.post("/editor/projects/{project_id}/render")
async def api_v1_render_editor_project(
    request: Request,
    project_id: int,
    body: EditorRenderBody | None = None,
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    payload = body or EditorRenderBody()
    try:
        done = render_editor_project(paths, project_id, style_preset=payload.style_preset)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return JSONResponse({"project": done})

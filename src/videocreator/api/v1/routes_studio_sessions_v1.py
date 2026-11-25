"""Studio Remotion interactive session endpoints for `/api/v1`."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from videocreator.api.v1.deps import resolve_workspace_id
from videocreator.db import query_one
from videocreator.paths import AppPaths
from videocreator.studio.session import (
    StudioBusyError,
    confirm_studio_plan,
    create_studio_session,
    enqueue_studio_job,
    list_studio_sessions,
    request_studio_revision,
)
from videocreator.studio.templates import (
    list_studio_templates,
    save_studio_template,
    start_render_from_template,
)

router = APIRouter()


class StudioSessionCreateBody(BaseModel):
    workspace_id: int | None = None
    prompt: str
    ref_item_id: int | None = None
    options: dict[str, Any] = Field(default_factory=dict)


class StudioRevisionBody(BaseModel):
    prompt: str


class StudioTemplateSaveBody(BaseModel):
    name: str
    props_schema: dict[str, Any] | None = None


class StudioTemplateRenderBody(BaseModel):
    shot_ids: list[int]
    subtitles: list[str] = Field(default_factory=list)
    title: str | None = None
    options: dict[str, Any] = Field(default_factory=dict)


@router.get("/studio/sessions")
async def api_v1_list_studio_sessions(
    request: Request,
    workspace_id: int | None = Query(default=None),
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    ws_id = resolve_workspace_id(paths.db_file, workspace_id)
    return JSONResponse(
        {"sessions": list_studio_sessions(paths.db_file, workspace_id=ws_id), "workspace_id": ws_id}
    )


@router.post("/studio/sessions", status_code=201)
async def api_v1_create_studio_session(
    request: Request, body: StudioSessionCreateBody
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    ws_id = resolve_workspace_id(paths.db_file, body.workspace_id, require_active=True)
    try:
        sid = create_studio_session(
            paths,
            prompt=body.prompt,
            ref_item_id=body.ref_item_id,
            options=body.options,
            workspace_id=ws_id,
            actor="api",
        )
    except StudioBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    job_id = enqueue_studio_job(paths.db_file, sid)
    sess = query_one(paths.db_file, "SELECT * FROM studio_sessions WHERE id = ?", (sid,))
    return JSONResponse({"session": sess, "job_id": job_id}, status_code=201)


@router.post("/studio/sessions/{session_id}/confirm")
async def api_v1_confirm_studio(request: Request, session_id: int) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    try:
        confirm_studio_plan(paths, session_id, actor="api")
    except StudioBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse({"confirmed": True, "session_id": session_id})


@router.post("/studio/sessions/{session_id}/revise")
async def api_v1_revise_studio(
    request: Request, session_id: int, body: StudioRevisionBody
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    try:
        request_studio_revision(paths, session_id, body.prompt, actor="api")
    except StudioBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse({"queued": True, "session_id": session_id})


@router.get("/studio/templates")
async def api_v1_list_studio_templates(request: Request) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    return JSONResponse({"templates": list_studio_templates(paths.db_file)})


@router.post("/studio/sessions/{session_id}/save-template", status_code=201)
async def api_v1_save_studio_template(
    request: Request, session_id: int, body: StudioTemplateSaveBody
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    try:
        tid = save_studio_template(
            paths,
            session_id,
            name=body.name,
            props_schema=body.props_schema,
            actor="api",
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    tpl = query_one(paths.db_file, "SELECT * FROM studio_templates WHERE id = ?", (tid,))
    return JSONResponse({"template_id": tid, "template": tpl}, status_code=201)


@router.post("/studio/templates/{template_id}/render", status_code=201)
async def api_v1_render_from_studio_template(
    request: Request, template_id: int, body: StudioTemplateRenderBody
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    try:
        sid = start_render_from_template(
            paths,
            template_id,
            shot_ids=body.shot_ids,
            subtitles=body.subtitles,
            title=body.title,
            options=body.options,
        )
    except StudioBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    sess = query_one(paths.db_file, "SELECT * FROM studio_sessions WHERE id = ?", (sid,))
    return JSONResponse({"session_id": sid, "session": sess}, status_code=201)

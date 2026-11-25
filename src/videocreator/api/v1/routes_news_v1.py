"""News / Article-to-Video Studio endpoints for `/api/v1`."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from videocreator.api.v1.deps import resolve_workspace_id
from videocreator.jobs import enqueue_job
from videocreator.paths import AppPaths
from videocreator.pipeline.news_studio import (
    create_news_project,
    get_news_project,
    list_news_projects,
    render_news_project,
    summarize_news_to_script,
    update_news_project,
)

router = APIRouter()


class NewsCreateBody(BaseModel):
    workspace_id: int | None = None
    title: str = ""
    source_kind: str = "raw_text"
    source_url: str = ""
    raw_text: str = ""
    character_id: int | None = None
    visual_source: str = "characters"
    style_preset: str = "tiktok_karaoke"
    aspect_ratio: str = "9:16"
    target_lang: str = "vi"
    voice_id: str = "vi-VN-HoaiMyNeural"


class NewsPatchBody(BaseModel):
    title: str | None = None
    script: list[dict[str, Any]] | None = None
    character_id: int | None = None
    visual_source: str | None = None
    style_preset: str | None = None
    aspect_ratio: str | None = None


class NewsRenderBody(BaseModel):
    sync: bool = False
    build_pack: bool = True
    visual_source: str | None = None


@router.get("/news/projects")
async def api_v1_list_news(
    request: Request,
    workspace_id: int | None = Query(default=None),
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    ws_id = resolve_workspace_id(paths.db_file, workspace_id)
    return JSONResponse(
        {"projects": list_news_projects(paths.db_file, workspace_id=ws_id), "workspace_id": ws_id}
    )


@router.post("/news/projects", status_code=201)
async def api_v1_create_news(
    request: Request, body: NewsCreateBody
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    ws_id = resolve_workspace_id(paths.db_file, body.workspace_id)
    try:
        proj = create_news_project(
            paths,
            workspace_id=ws_id,
            title=body.title,
            source_kind=body.source_kind,
            source_url=body.source_url,
            raw_text=body.raw_text,
            character_id=body.character_id,
            visual_source=body.visual_source,
            style_preset=body.style_preset,
            aspect_ratio=body.aspect_ratio,
            target_lang=body.target_lang,
            voice_id=body.voice_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse({"project": proj}, status_code=201)


@router.get("/news/projects/{project_id}")
async def api_v1_get_news(request: Request, project_id: int) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    proj = get_news_project(paths.db_file, project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail=f"News project #{project_id} not found")
    return JSONResponse({"project": proj})


@router.patch("/news/projects/{project_id}")
async def api_v1_patch_news(
    request: Request, project_id: int, body: NewsPatchBody
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    try:
        proj = update_news_project(
            paths,
            project_id,
            title=body.title,
            script=body.script,
            character_id=body.character_id,
            visual_source=body.visual_source,
            style_preset=body.style_preset,
            aspect_ratio=body.aspect_ratio,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if proj is None:
        raise HTTPException(status_code=404, detail=f"News project #{project_id} not found")
    return JSONResponse({"project": proj})


@router.post("/news/projects/{project_id}/summarize")
async def api_v1_summarize_news(request: Request, project_id: int) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    try:
        proj = summarize_news_to_script(paths, project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse({"project": proj})


@router.post("/news/projects/{project_id}/render")
async def api_v1_render_news(
    request: Request,
    project_id: int,
    body: NewsRenderBody | None = None,
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    proj = get_news_project(paths.db_file, project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail=f"News project #{project_id} not found")
    payload = body or NewsRenderBody()
    if payload.visual_source:
        try:
            update_news_project(paths, project_id, visual_source=payload.visual_source)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if payload.sync:
        try:
            done = render_news_project(
                paths, project_id, build_pack=payload.build_pack, visual_source=payload.visual_source
            )
            return JSONResponse({"project": done, "job_id": None})
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    job_id = enqueue_job(
        paths.db_file,
        "news_render",
        ref_id=project_id,
        lane="compute",
        workspace_id=int(proj["workspace_id"]),
    )
    return JSONResponse({"project": proj, "job_id": job_id}, status_code=202)

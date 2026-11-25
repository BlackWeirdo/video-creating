"""Localize, Reup, Hybrid Remix & Internationalize Studio endpoints for `/api/v1`."""
from __future__ import annotations

import secrets
from typing import Any

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from videocreator.api.v1.deps import resolve_workspace_id
from videocreator.api.v1.uploads import MAX_LOCALIZE_UPLOAD_BYTES, read_upload_bytes_checked
from videocreator.jobs import enqueue_job
from videocreator.paths import AppPaths
from videocreator.pipeline.localize import (
    create_localize_project,
    get_localize_project,
    list_localize_projects,
    preview_localize_segment_audio,
    run_localize_extract,
    run_localize_render,
    update_localize_project,
)

router = APIRouter()


class LocalizeCreateBody(BaseModel):
    workspace_id: int | None = None
    title: str
    mode: str = "reup_vi"
    source_url: str = ""
    source_media_path: str = ""
    source_trend_id: int | None = None
    source_video_id: int | None = None
    source_lang: str = "auto"
    target_lang: str = "vi"
    hardsub_mode: str = "blur_bar"
    hardsub_box: dict[str, float] | None = None
    anti_dup: dict[str, Any] | None = None
    product_ids: list[int] = Field(default_factory=list)
    style_preset: str = "tiktok_karaoke"
    aspect_ratio: str = "9:16"
    voice_id: str = "vi-VN-HoaiMyNeural"
    whisper_size: str = "small"
    translation_style: str = "natural_tiktok"
    clone_source_voice: bool = False
    clone_consent_confirmed: bool = False


class LocalizePatchBody(BaseModel):
    title: str | None = None
    target_lang: str | None = None
    hardsub_mode: str | None = None
    hardsub_box: dict[str, float] | None = None
    anti_dup: dict[str, Any] | None = None
    segments: list[dict[str, Any]] | None = None
    product_ids: list[int] | None = None
    style_preset: str | None = None
    aspect_ratio: str | None = None
    voice_id: str | None = None
    whisper_size: str | None = None
    translation_style: str | None = None
    clone_source_voice: bool | None = None
    clone_consent_confirmed: bool | None = None
    speaker_config: dict[str, Any] | None = None


class LocalizeRunBody(BaseModel):
    sync: bool = False
    tts_provider: str = "auto"
    target_accounts: list[int] = Field(default_factory=list)


class LocalizePreviewBody(BaseModel):
    segment_index: int
    tts_provider: str = "auto"


@router.get("/localize/projects")
async def api_v1_list_localize(
    request: Request,
    workspace_id: int | None = Query(default=None),
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    ws_id = resolve_workspace_id(paths.db_file, workspace_id)
    return JSONResponse(
        {
            "projects": list_localize_projects(paths.db_file, workspace_id=ws_id),
            "workspace_id": ws_id,
        }
    )


@router.post("/localize/projects", status_code=201)
async def api_v1_create_localize(
    request: Request, body: LocalizeCreateBody
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    ws_id = resolve_workspace_id(paths.db_file, body.workspace_id)
    try:
        proj = create_localize_project(
            paths,
            workspace_id=ws_id,
            title=body.title,
            mode=body.mode,
            source_url=body.source_url,
            source_media_path=body.source_media_path,
            source_trend_id=body.source_trend_id,
            source_video_id=body.source_video_id,
            source_lang=body.source_lang,
            target_lang=body.target_lang,
            hardsub_mode=body.hardsub_mode,
            hardsub_box=body.hardsub_box,
            anti_dup=body.anti_dup,
            product_ids=body.product_ids,
            style_preset=body.style_preset,
            aspect_ratio=body.aspect_ratio,
            voice_id=body.voice_id,
            whisper_size=body.whisper_size,
            translation_style=body.translation_style,
            clone_source_voice=body.clone_source_voice,
            clone_consent_confirmed=body.clone_consent_confirmed,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse({"project": proj}, status_code=201)


@router.post("/localize/upload", status_code=201)
async def api_v1_upload_localize_source(
    request: Request,
    file: UploadFile = File(...),
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    data, suffix = await read_upload_bytes_checked(
        file,
        allowed_extensions=(".mp4", ".mov", ".mkv", ".webm", ".m4v"),
        min_bytes=64,
        max_bytes=MAX_LOCALIZE_UPLOAD_BYTES,
        invalid_ext_message="Chỉ hỗ trợ file video (.mp4/.mov/.mkv/.webm)",
        empty_message="File video tải lên rỗng",
    )
    dest_dir = paths.media_dir / "localize" / "uploads"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_name = f"loc_{secrets.token_hex(6)}{suffix}"
    dest = dest_dir / dest_name
    dest.write_bytes(data)
    rel_path = f"localize/uploads/{dest_name}"
    return JSONResponse(
        {"source_media_path": rel_path, "bytes": len(data)},
        status_code=201,
    )


@router.get("/localize/projects/{project_id}")
async def api_v1_get_localize(
    request: Request, project_id: int
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    proj = get_localize_project(paths.db_file, project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail=f"Localize project #{project_id} not found")
    return JSONResponse({"project": proj})


@router.patch("/localize/projects/{project_id}")
async def api_v1_patch_localize(
    request: Request, project_id: int, body: LocalizePatchBody
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    try:
        proj = update_localize_project(
            paths,
            project_id,
            title=body.title,
            target_lang=body.target_lang,
            hardsub_mode=body.hardsub_mode,
            hardsub_box=body.hardsub_box,
            anti_dup=body.anti_dup,
            segments=body.segments,
            product_ids=body.product_ids,
            style_preset=body.style_preset,
            aspect_ratio=body.aspect_ratio,
            voice_id=body.voice_id,
            whisper_size=body.whisper_size,
            translation_style=body.translation_style,
            clone_source_voice=body.clone_source_voice,
            clone_consent_confirmed=body.clone_consent_confirmed,
            speaker_config=body.speaker_config,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if proj is None:
        raise HTTPException(status_code=404, detail=f"Localize project #{project_id} not found")
    return JSONResponse({"project": proj})


@router.post("/localize/projects/{project_id}/preview-segment")
async def api_v1_preview_localize_segment(
    request: Request, project_id: int, body: LocalizePreviewBody
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    try:
        res = preview_localize_segment_audio(
            paths,
            project_id,
            body.segment_index,
            tts_provider=body.tts_provider,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(res)


@router.post("/localize/projects/{project_id}/extract")
async def api_v1_extract_localize(
    request: Request, project_id: int, body: LocalizeRunBody | None = None
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    proj = get_localize_project(paths.db_file, project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail=f"Localize project #{project_id} not found")
    payload = body or LocalizeRunBody()
    if payload.sync:
        try:
            updated = run_localize_extract(paths, project_id)
            return JSONResponse({"project": updated, "job_id": None})
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    job_id = enqueue_job(
        paths.db_file,
        "localize_extract",
        ref_id=project_id,
        lane="compute",
        workspace_id=int(proj["workspace_id"]),
    )
    return JSONResponse({"project": proj, "job_id": job_id}, status_code=202)


@router.post("/localize/projects/{project_id}/render")
async def api_v1_render_localize(
    request: Request, project_id: int, body: LocalizeRunBody | None = None
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    proj = get_localize_project(paths.db_file, project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail=f"Localize project #{project_id} not found")
    payload = body or LocalizeRunBody()
    if payload.sync:
        try:
            updated = run_localize_render(
                paths,
                project_id,
                tts_provider=payload.tts_provider,
                target_accounts=payload.target_accounts,
            )
            return JSONResponse({"project": updated, "job_id": None})
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    job_id = enqueue_job(
        paths.db_file,
        "localize_render",
        ref_id=project_id,
        lane="compute",
        workspace_id=int(proj["workspace_id"]),
    )
    return JSONResponse({"project": proj, "job_id": job_id}, status_code=202)

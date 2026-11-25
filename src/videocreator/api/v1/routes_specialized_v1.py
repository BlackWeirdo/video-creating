"""Specialized Studios endpoints (`/api/v1/novels`, `/api/v1/podcasts`, `/api/v1/lipsync`)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from videocreator.api.v1.deps import resolve_workspace_id
from videocreator.db import get_conn
from videocreator.jobs import enqueue_job
from videocreator.paths import AppPaths
from videocreator.pipeline.lipsync_studio import (
    create_lipsync_project,
    get_lipsync_project,
    list_lipsync_projects,
    render_lipsync_project,
)
from videocreator.pipeline.novel_studio import (
    create_novel_project,
    get_novel_project,
    list_novel_projects,
    render_novel_project,
    split_novel_chapters,
)
from videocreator.pipeline.podcast_studio import (
    create_podcast_project,
    get_podcast_project,
    list_podcast_projects,
    render_podcast_project,
)

router = APIRouter()


class NovelSplitPreviewBody(BaseModel):
    source_text: str
    target_words_per_chapter: int = 140


class NovelCreateBody(BaseModel):
    workspace_id: int | None = None
    title: str = ""
    source_text: str
    character_id: int | None = None
    visual_source: str = "characters"
    style_preset: str = "tiktok_karaoke"
    aspect_ratio: str = "9:16"
    target_lang: str = "vi"
    voice_id: str = "vi-VN-HoaiMyNeural"
    target_words_per_chapter: int = 140


class NovelRenderBody(BaseModel):
    chapter_ids: list[int] | None = None
    force: bool = False
    sync: bool = False
    visual_source: str | None = None


class PodcastCreateBody(BaseModel):
    workspace_id: int | None = None
    title: str = "Podcast Studio Episode"
    dialogue: list[dict[str, Any]] | None = None
    script_text: str = ""
    host_a_name: str = "Host A"
    host_b_name: str = "Host B"
    host_a_voice: str = "vi-VN-HoaiMyNeural"
    host_b_voice: str = "vi-VN-NamMinhNeural"
    host_a_avatar_path: str = ""
    host_b_avatar_path: str = ""
    audio_source_path: str = ""
    aspect_ratio: str = "16:9"
    waveform_style: str = "cline"
    accent_color: str = "#38bdf8"
    style_preset: str = "minimal_bottom"
    target_lang: str = "vi"


class LipsyncCreateBody(BaseModel):
    workspace_id: int | None = None
    title: str = "Lip-sync AI Video"
    character_id: int | None = None
    portrait_path: str = ""
    script_text: str = ""
    audio_path: str = ""
    aspect_ratio: str = "9:16"
    style_preset: str = "tiktok_karaoke"
    target_lang: str = "vi"
    voice_id: str = "vi-VN-HoaiMyNeural"


class SyncRenderBody(BaseModel):
    tts_provider: str | None = None
    sync: bool = False


# ---------------------------------------------------------------------------
# Novel-to-Video Studio
# ---------------------------------------------------------------------------


@router.post("/novels/split-preview")
async def api_v1_split_novel_preview(body: NovelSplitPreviewBody) -> JSONResponse:
    chapters = split_novel_chapters(
        body.source_text, target_words=body.target_words_per_chapter
    )
    return JSONResponse({"chapters": chapters, "total_chapters": len(chapters)})


@router.get("/novels/projects")
async def api_v1_list_novels(
    request: Request,
    workspace_id: int | None = Query(default=None),
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    ws_id = resolve_workspace_id(paths.db_file, workspace_id)
    return JSONResponse(
        {"projects": list_novel_projects(paths.db_file, workspace_id=ws_id), "workspace_id": ws_id}
    )


@router.post("/novels/projects", status_code=201)
async def api_v1_create_novel(request: Request, body: NovelCreateBody) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    ws_id = resolve_workspace_id(paths.db_file, body.workspace_id)
    try:
        proj = create_novel_project(
            paths,
            workspace_id=ws_id,
            title=body.title,
            source_text=body.source_text,
            character_id=body.character_id,
            visual_source=body.visual_source,
            style_preset=body.style_preset,
            aspect_ratio=body.aspect_ratio,
            target_lang=body.target_lang,
            voice_id=body.voice_id,
            target_words_per_chapter=body.target_words_per_chapter,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse({"project": proj}, status_code=201)


@router.get("/novels/projects/{project_id}")
async def api_v1_get_novel(request: Request, project_id: int) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    proj = get_novel_project(paths.db_file, project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail=f"Novel project #{project_id} not found")
    return JSONResponse({"project": proj})


@router.post("/novels/projects/{project_id}/render")
async def api_v1_render_novel(
    request: Request, project_id: int, body: NovelRenderBody
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    proj = get_novel_project(paths.db_file, project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail=f"Novel project #{project_id} not found")
    if body.visual_source:
        vs = body.visual_source.strip().lower()
        if vs not in ("characters", "muse_video"):
            raise HTTPException(status_code=400, detail=f"Unsupported novel visual_source '{body.visual_source}'")
        with get_conn(paths.db_file) as conn:
            conn.execute("UPDATE novel_projects SET visual_source = ? WHERE id = ?", (vs, int(project_id)))

    if body.sync:
        try:
            done = render_novel_project(
                paths,
                project_id,
                chapter_ids=body.chapter_ids,
                force=body.force,
                visual_source=body.visual_source,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse({"project": done})

    if body.force:
        with get_conn(paths.db_file) as conn:
            if body.chapter_ids:
                placeholders = ",".join("?" * len(body.chapter_ids))
                conn.execute(
                    f"UPDATE novel_chapters SET status = 'pending', error = NULL WHERE project_id = ? AND id IN ({placeholders})",
                    (int(project_id), *[int(c) for c in body.chapter_ids]),
                )
            else:
                conn.execute(
                    "UPDATE novel_chapters SET status = 'pending', error = NULL WHERE project_id = ?",
                    (int(project_id),),
                )
    job_id = enqueue_job(
        paths.db_file,
        "novel_render",
        ref_id=int(project_id),
        workspace_id=int(proj["workspace_id"]),
    )
    return JSONResponse(
        {"job_id": job_id, "project_id": project_id, "status": "queued"},
        status_code=202,
    )


# ---------------------------------------------------------------------------
# Podcast Audio-Spectrum Studio
# ---------------------------------------------------------------------------


@router.get("/podcasts/projects")
async def api_v1_list_podcasts(
    request: Request,
    workspace_id: int | None = Query(default=None),
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    ws_id = resolve_workspace_id(paths.db_file, workspace_id)
    return JSONResponse(
        {"projects": list_podcast_projects(paths.db_file, workspace_id=ws_id), "workspace_id": ws_id}
    )


@router.post("/podcasts/projects", status_code=201)
async def api_v1_create_podcast(request: Request, body: PodcastCreateBody) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    ws_id = resolve_workspace_id(paths.db_file, body.workspace_id)
    try:
        proj = create_podcast_project(
            paths,
            workspace_id=ws_id,
            title=body.title,
            dialogue=body.dialogue,
            script_text=body.script_text,
            host_a_name=body.host_a_name,
            host_b_name=body.host_b_name,
            host_a_voice=body.host_a_voice,
            host_b_voice=body.host_b_voice,
            host_a_avatar_path=body.host_a_avatar_path,
            host_b_avatar_path=body.host_b_avatar_path,
            audio_source_path=body.audio_source_path,
            aspect_ratio=body.aspect_ratio,
            waveform_style=body.waveform_style,
            accent_color=body.accent_color,
            style_preset=body.style_preset,
            target_lang=body.target_lang,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse({"project": proj}, status_code=201)


@router.get("/podcasts/projects/{project_id}")
async def api_v1_get_podcast(request: Request, project_id: int) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    proj = get_podcast_project(paths.db_file, project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail=f"Podcast project #{project_id} not found")
    return JSONResponse({"project": proj})


@router.post("/podcasts/projects/{project_id}/render")
async def api_v1_render_podcast(
    request: Request, project_id: int, body: SyncRenderBody
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    proj = get_podcast_project(paths.db_file, project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail=f"Podcast project #{project_id} not found")
    if body.sync:
        try:
            done = render_podcast_project(
                paths, project_id, tts_provider=body.tts_provider
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse({"project": done})

    job_id = enqueue_job(
        paths.db_file,
        "podcast_render",
        ref_id=int(project_id),
        workspace_id=int(proj["workspace_id"]),
    )
    return JSONResponse(
        {"job_id": job_id, "project_id": project_id, "status": "queued"},
        status_code=202,
    )


# ---------------------------------------------------------------------------
# Lip-sync AI Studio
# ---------------------------------------------------------------------------


@router.get("/lipsync/projects")
async def api_v1_list_lipsync(
    request: Request,
    workspace_id: int | None = Query(default=None),
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    ws_id = resolve_workspace_id(paths.db_file, workspace_id)
    return JSONResponse(
        {"projects": list_lipsync_projects(paths.db_file, workspace_id=ws_id), "workspace_id": ws_id}
    )


@router.post("/lipsync/projects", status_code=201)
async def api_v1_create_lipsync(request: Request, body: LipsyncCreateBody) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    ws_id = resolve_workspace_id(paths.db_file, body.workspace_id)
    try:
        proj = create_lipsync_project(
            paths,
            workspace_id=ws_id,
            title=body.title,
            character_id=body.character_id,
            portrait_path=body.portrait_path,
            script_text=body.script_text,
            audio_path=body.audio_path,
            aspect_ratio=body.aspect_ratio,
            style_preset=body.style_preset,
            target_lang=body.target_lang,
            voice_id=body.voice_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse({"project": proj}, status_code=201)


@router.get("/lipsync/projects/{project_id}")
async def api_v1_get_lipsync(request: Request, project_id: int) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    proj = get_lipsync_project(paths.db_file, project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail=f"Lip-sync project #{project_id} not found")
    return JSONResponse({"project": proj})


@router.post("/lipsync/projects/{project_id}/upload-portrait")
async def api_v1_upload_lipsync_portrait(
    request: Request, project_id: int, file: UploadFile = File(...)
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    proj = get_lipsync_project(paths.db_file, project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail=f"Lip-sync project #{project_id} not found")
    suffix = Path(file.filename or "portrait.png").suffix.lower()
    if suffix not in (".png", ".jpg", ".jpeg", ".webp"):
        raise HTTPException(status_code=400, detail="Chỉ hỗ trợ ảnh .png / .jpg / .webp")
    dest_dir = paths.media_dir / "characters"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"lipsync_{project_id}_portrait{suffix}"
    dest.write_bytes(await file.read())
    rel = f"characters/{dest.name}"
    with get_conn(paths.db_file) as conn:
        conn.execute(
            "UPDATE lipsync_projects SET portrait_path = ? WHERE id = ?",
            (rel, int(project_id)),
        )
    updated = get_lipsync_project(paths.db_file, project_id)
    return JSONResponse({"project": updated})


@router.post("/lipsync/projects/{project_id}/render")
async def api_v1_render_lipsync(
    request: Request, project_id: int, body: SyncRenderBody
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    proj = get_lipsync_project(paths.db_file, project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail=f"Lip-sync project #{project_id} not found")
    if body.sync:
        try:
            done = render_lipsync_project(
                paths, project_id, tts_provider=body.tts_provider
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse({"project": done})

    job_id = enqueue_job(
        paths.db_file,
        "lipsync_render",
        ref_id=int(project_id),
        workspace_id=int(proj["workspace_id"]),
    )
    return JSONResponse(
        {"job_id": job_id, "project_id": project_id, "status": "queued"},
        status_code=202,
    )

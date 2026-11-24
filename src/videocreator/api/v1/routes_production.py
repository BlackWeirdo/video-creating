"""Video Styles, Production (`videos`), Render/Restyle/QC & Studio Remotion endpoints for `/api/v1`."""
from __future__ import annotations

import asyncio
import json
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from videocreator.api.v1.deps import resolve_workspace_id, serialize_v1_video
from videocreator.db import get_conn, query_all, query_one, record_audit
from videocreator.jobs import enqueue_job
from videocreator.jsonutil import loads_or
from videocreator.paths import AppPaths
from videocreator.pipeline.qc import run_video_qc
from videocreator.pipeline.render import render_video
from videocreator.pipeline.restyle import restyle_video
from videocreator.pipeline.styles import (
    create_style_preset,
    delete_style_preset,
    get_style_preset,
    list_style_presets,
    update_style_preset,
)
from videocreator.products import product_name_map
from videocreator.studio.session import (
    StudioBusyError,
    confirm_studio_plan,
    create_studio_session,
    enqueue_studio_job,
    list_studio_sessions,
    request_studio_revision,
)

router = APIRouter()


class StyleCreateBody(BaseModel):
    name: str
    preset_id: str = ""
    workspace_id: int | None = None
    subtitle_style: str = "karaoke_highlight"
    font_name: str = "Be Vietnam Pro"
    font_size: int = Field(default=58, ge=24, le=120)
    primary_color: str = "#FFFFFF"
    highlight_color: str = "#FFE082"
    outline_color: str = "#141414"
    box_color: str = "#99121216"
    position: str = "bottom"
    ducking_enabled: bool = True
    music_volume: float = Field(default=0.22, ge=0.0, le=1.0)
    sfx_transition_asset_id: int | None = None
    intro_text: str = ""
    outro_text: str = ""
    motion_preset: str = "none"


class StyleUpdateBody(BaseModel):
    name: str | None = None
    subtitle_style: str | None = None
    font_name: str | None = None
    font_size: int | None = Field(default=None, ge=24, le=120)
    primary_color: str | None = None
    highlight_color: str | None = None
    outline_color: str | None = None
    box_color: str | None = None
    position: str | None = None
    ducking_enabled: bool | None = None
    music_volume: float | None = Field(default=None, ge=0.0, le=1.0)
    sfx_transition_asset_id: int | None = None
    clear_sfx: bool = False
    intro_text: str | None = None
    outro_text: str | None = None
    motion_preset: str | None = None


class VideoCreateBody(BaseModel):
    workspace_id: int | None = None
    footage_id: int | None = None
    product_ids: list[int] = Field(default_factory=list)
    engine: Literal["ffmpeg", "studio"] = "ffmpeg"
    style_preset: str = ""
    aspect_ratio: Literal["9:16", "16:9", "1:1"] = "9:16"
    voice_lang: Literal["none", "vi", "en"] = "none"
    caption_lang: Literal["vi", "en"] = "vi"
    plan: dict[str, Any] = Field(default_factory=dict)
    captions: dict[str, Any] = Field(default_factory=dict)


class VideoUpdateBody(BaseModel):
    title: str | None = None
    plan: dict[str, Any] | None = None
    shots: list[dict[str, Any]] | None = None
    captions: dict[str, Any] | None = None
    style_preset: str | None = None
    aspect_ratio: Literal["9:16", "16:9", "1:1"] | None = None
    voice_lang: Literal["none", "vi", "en"] | None = None
    caption_lang: Literal["vi", "en"] | None = None
    clear_unverified: bool = False


class VideoRenderBody(BaseModel):
    music_asset_id: int | None = None
    preset: str = "veryfast"
    sync: bool = False


class VideoRestyleBody(BaseModel):
    style_preset: str
    music_asset_id: int | None = None
    preset: str = "veryfast"
    sync: bool = False


class StudioSessionCreateBody(BaseModel):
    workspace_id: int | None = None
    prompt: str
    ref_item_id: int | None = None
    options: dict[str, Any] = Field(default_factory=dict)


class StudioRevisionBody(BaseModel):
    prompt: str


# ---------- Video Style Presets ----------


@router.get("/styles")
async def api_v1_list_styles(
    request: Request,
    workspace_id: int | None = Query(default=None),
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    ws_id = resolve_workspace_id(paths.db_file, workspace_id)
    return JSONResponse(
        {"styles": list_style_presets(paths.db_file, workspace_id=ws_id), "workspace_id": ws_id}
    )


@router.post("/styles", status_code=201)
async def api_v1_create_style(
    request: Request, body: StyleCreateBody
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    ws_id = (
        resolve_workspace_id(paths.db_file, body.workspace_id, require_active=True)
        if body.workspace_id is not None
        else None
    )
    try:
        created = create_style_preset(
            paths.db_file,
            name=body.name,
            preset_id=body.preset_id,
            workspace_id=ws_id,
            subtitle_style=body.subtitle_style,
            font_name=body.font_name,
            font_size=body.font_size,
            primary_color=body.primary_color,
            highlight_color=body.highlight_color,
            outline_color=body.outline_color,
            box_color=body.box_color,
            position=body.position,
            ducking_enabled=body.ducking_enabled,
            music_volume=body.music_volume,
            sfx_transition_asset_id=body.sfx_transition_asset_id,
            intro_text=body.intro_text,
            outro_text=body.outro_text,
            motion_preset=body.motion_preset,
            actor="api",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse({"style": created}, status_code=201)


@router.patch("/styles/{preset_id}")
async def api_v1_update_style(
    request: Request, preset_id: str, body: StyleUpdateBody
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    try:
        updated = update_style_preset(
            paths.db_file,
            preset_id,
            name=body.name,
            subtitle_style=body.subtitle_style,
            font_name=body.font_name,
            font_size=body.font_size,
            primary_color=body.primary_color,
            highlight_color=body.highlight_color,
            outline_color=body.outline_color,
            box_color=body.box_color,
            position=body.position,
            ducking_enabled=body.ducking_enabled,
            music_volume=body.music_volume,
            sfx_transition_asset_id=body.sfx_transition_asset_id,
            clear_sfx=body.clear_sfx,
            intro_text=body.intro_text,
            outro_text=body.outro_text,
            motion_preset=body.motion_preset,
            actor="api",
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse({"style": updated})


@router.delete("/styles/{preset_id}")
async def api_v1_delete_style(request: Request, preset_id: str) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    try:
        delete_style_preset(paths.db_file, preset_id, actor="api")
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse({"deleted": True, "style_id": preset_id})


# ---------- Videos ----------


@router.get("/videos")
async def api_v1_list_videos(
    request: Request,
    workspace_id: int | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    ws_id = resolve_workspace_id(paths.db_file, workspace_id)
    pmap = product_name_map(paths.db_file, workspace_id=ws_id)
    sql = "SELECT * FROM videos WHERE workspace_id = ?"
    params: list[Any] = [ws_id]
    if status:
        sql += " AND status = ?"
        params.append(status.strip())
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    rows = query_all(paths.db_file, sql, params)
    return JSONResponse(
        {
            "videos": [serialize_v1_video(r, product_map=pmap) for r in rows],
            "workspace_id": ws_id,
        }
    )


@router.post("/videos", status_code=201)
async def api_v1_create_video(
    request: Request, body: VideoCreateBody
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    ws_id = resolve_workspace_id(paths.db_file, body.workspace_id, require_active=True)
    ws_row = query_one(
        paths.db_file, "SELECT style_preset FROM workspaces WHERE id = ?", (ws_id,)
    )
    chosen_style = (
        body.style_preset.strip()
        or (str(ws_row["style_preset"]) if ws_row and ws_row.get("style_preset") else "tiktok_karaoke")
    )
    if get_style_preset(paths.db_file, chosen_style) is None:
        raise HTTPException(status_code=400, detail=f"Style preset '{chosen_style}' not found")

    clean_pids = sorted({int(x) for x in body.product_ids if int(x) > 0})
    with get_conn(paths.db_file) as conn:
        cur = conn.execute(
            """
            INSERT INTO videos (
                workspace_id, footage_id, product_ids_json, engine, status,
                plan_json, captions_json, voice_lang, caption_lang,
                style_preset, aspect_ratio
            )
            VALUES (?, ?, ?, ?, 'planned', ?, ?, ?, ?, ?, ?)
            """,
            (
                ws_id,
                body.footage_id,
                json.dumps(clean_pids),
                body.engine,
                json.dumps(body.plan or {}, ensure_ascii=False),
                json.dumps(body.captions or {}, ensure_ascii=False),
                body.voice_lang,
                body.caption_lang,
                chosen_style,
                body.aspect_ratio,
            ),
        )
        vid = int(cur.lastrowid or 0)
        record_audit(
            conn,
            actor="api",
            action="video.created",
            object_type="video",
            object_id=vid,
            detail=f"ws={ws_id}, style={chosen_style}, ratio={body.aspect_ratio}",
        )
    row = query_one(paths.db_file, "SELECT * FROM videos WHERE id = ?", (vid,))
    assert row is not None
    pmap = product_name_map(paths.db_file, workspace_id=ws_id)
    return JSONResponse({"video": serialize_v1_video(row, product_map=pmap)}, status_code=201)


@router.get("/videos/{video_id}")
async def api_v1_get_video(request: Request, video_id: int) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    row = query_one(paths.db_file, "SELECT * FROM videos WHERE id = ?", (video_id,))
    if row is None:
        raise HTTPException(status_code=404, detail=f"Video #{video_id} not found")
    ws_id = int(row.get("workspace_id") or 1)
    pmap = product_name_map(paths.db_file, workspace_id=ws_id)
    return JSONResponse({"video": serialize_v1_video(row, product_map=pmap)})


@router.patch("/videos/{video_id}")
async def api_v1_update_video(
    request: Request, video_id: int, body: VideoUpdateBody
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    row = query_one(paths.db_file, "SELECT * FROM videos WHERE id = ?", (video_id,))
    if row is None:
        raise HTTPException(status_code=404, detail=f"Video #{video_id} not found")

    plan = loads_or(row.get("plan_json"), {})
    if not isinstance(plan, dict):
        plan = {}
    if body.plan is not None:
        plan = dict(body.plan)
    if body.title is not None:
        plan["title"] = body.title.strip()
    if body.shots is not None:
        plan["shots"] = body.shots

    captions = (
        dict(body.captions)
        if body.captions is not None
        else loads_or(row.get("captions_json"), {})
    )
    if body.captions is not None:
        plan["captions"] = captions

    next_style = body.style_preset.strip() if body.style_preset is not None else str(row.get("style_preset") or "tiktok_karaoke")
    if get_style_preset(paths.db_file, next_style) is None:
        raise HTTPException(status_code=400, detail=f"Style preset '{next_style}' not found")

    next_ratio = body.aspect_ratio or str(row.get("aspect_ratio") or "9:16")
    next_vlang = body.voice_lang or str(row.get("voice_lang") or "none")
    next_clang = body.caption_lang or str(row.get("caption_lang") or "vi")
    if body.clear_unverified:
        plan["unverified_claims"] = []
        claims_json = "[]"
    else:
        claims_json = str(row.get("unsupported_claims_json") or "[]")

    with get_conn(paths.db_file) as conn:
        conn.execute(
            """
            UPDATE videos
            SET plan_json = ?,
                captions_json = ?,
                style_preset = ?,
                aspect_ratio = ?,
                voice_lang = ?,
                caption_lang = ?,
                unsupported_claims_json = ?
            WHERE id = ?
            """,
            (
                json.dumps(plan, ensure_ascii=False),
                json.dumps(captions, ensure_ascii=False),
                next_style,
                next_ratio,
                next_vlang,
                next_clang,
                claims_json,
                video_id,
            ),
        )
        record_audit(
            conn,
            actor="api",
            action="video.updated",
            object_type="video",
            object_id=video_id,
            detail=f"style={next_style}, ratio={next_ratio}",
        )
    updated = query_one(paths.db_file, "SELECT * FROM videos WHERE id = ?", (video_id,))
    assert updated is not None
    pmap = product_name_map(paths.db_file, workspace_id=int(updated.get("workspace_id") or 1))
    return JSONResponse({"video": serialize_v1_video(updated, product_map=pmap)})


@router.post("/videos/{video_id}/render")
async def api_v1_render_video(
    request: Request,
    video_id: int,
    sync: bool = Query(default=False),
    body: VideoRenderBody | None = None,
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    row = query_one(paths.db_file, "SELECT * FROM videos WHERE id = ?", (video_id,))
    if row is None:
        raise HTTPException(status_code=404, detail=f"Video #{video_id} not found")
    ws_id = int(row.get("workspace_id") or 1)
    run_sync = sync or (body is not None and body.sync)
    if run_sync:
        summary = await asyncio.to_thread(
            render_video,
            paths,
            video_id,
            preset=body.preset if body else "veryfast",
            music_asset_id=body.music_asset_id if body else None,
        )
        fresh = query_one(paths.db_file, "SELECT * FROM videos WHERE id = ?", (video_id,))
        assert fresh is not None
        return JSONResponse(
            {
                "mode": "sync",
                "summary": summary,
                "video": serialize_v1_video(
                    fresh, product_map=product_name_map(paths.db_file, workspace_id=ws_id)
                ),
            }
        )
    job_id = enqueue_job(
        paths.db_file, "render", ref_id=video_id, lane="compute", workspace_id=ws_id
    )
    return JSONResponse({"mode": "queued", "job_id": job_id, "video_id": video_id})


@router.post("/videos/{video_id}/restyle")
async def api_v1_restyle_video(
    request: Request,
    video_id: int,
    body: VideoRestyleBody,
    sync: bool = Query(default=False),
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    row = query_one(paths.db_file, "SELECT * FROM videos WHERE id = ?", (video_id,))
    if row is None:
        raise HTTPException(status_code=404, detail=f"Video #{video_id} not found")
    if get_style_preset(paths.db_file, body.style_preset) is None:
        raise HTTPException(status_code=400, detail=f"Style preset '{body.style_preset}' not found")
    ws_id = int(row.get("workspace_id") or 1)
    run_sync = sync or body.sync
    if run_sync:
        try:
            summary = await asyncio.to_thread(
                restyle_video,
                paths,
                video_id,
                body.style_preset,
                music_asset_id=body.music_asset_id,
                preset=body.preset,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        fresh = query_one(paths.db_file, "SELECT * FROM videos WHERE id = ?", (video_id,))
        assert fresh is not None
        return JSONResponse(
            {
                "mode": "sync",
                "summary": summary,
                "video": serialize_v1_video(
                    fresh, product_map=product_name_map(paths.db_file, workspace_id=ws_id)
                ),
            }
        )
    with get_conn(paths.db_file) as conn:
        conn.execute(
            "UPDATE videos SET style_preset = ? WHERE id = ?",
            (body.style_preset.strip(), video_id),
        )
    job_id = enqueue_job(
        paths.db_file, "restyle_video", ref_id=video_id, lane="compute", workspace_id=ws_id
    )
    return JSONResponse({"mode": "queued", "job_id": job_id, "video_id": video_id})


@router.post("/videos/{video_id}/qc")
async def api_v1_run_video_qc(request: Request, video_id: int) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    row = query_one(paths.db_file, "SELECT * FROM videos WHERE id = ?", (video_id,))
    if row is None:
        raise HTTPException(status_code=404, detail=f"Video #{video_id} not found")
    if not row.get("output_path"):
        raise HTTPException(status_code=400, detail=f"Video #{video_id} has not been rendered yet")
    mp4 = paths.media_dir / str(row["output_path"])
    qc = await asyncio.to_thread(
        run_video_qc, mp4, expect_voice=str(row.get("voice_lang") or "none") in ("vi", "en")
    )
    with get_conn(paths.db_file) as conn:
        conn.execute(
            "UPDATE videos SET qc_json = ? WHERE id = ?",
            (json.dumps(qc, ensure_ascii=False), video_id),
        )
    return JSONResponse({"video_id": video_id, "qc": qc})


# ---------- Studio Sessions ----------


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

"""Muse Studio, Queue, Storyboards, Pairing & Sidecar endpoints (`/api/v1/muse/*`)."""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from videocreator.ai.budget import budget_day
from videocreator.api.v1.deps import resolve_workspace_id
from videocreator.config import load_settings
from videocreator.db import query_one
from videocreator.muse_gateway.admin import get_muse_pool, list_muse_combos
from videocreator.muse_gateway.capacity import compute_gateway_capacity
from videocreator.muse_gateway.client import MuseGatewayClient
from videocreator.muse_gateway.dispatcher import run_muse_dispatcher_tick
from videocreator.muse_gateway.errors import (
    MuseAuthError,
    MuseGatewayError,
    MuseInputError,
    MuseUnavailable,
    MuseUnsafeGatewayError,
)
from videocreator.muse_gateway.media_import import import_completed_muse_task
from videocreator.muse_gateway.pairing import poll_gateway_pairing, start_gateway_pairing
from videocreator.muse_gateway.refs import stage_uploaded_muse_ref, validate_muse_refs_policy
from videocreator.muse_gateway.sidecar import (
    ensure_muse_sidecar_running,
    get_sidecar_runtime_status,
    stop_muse_sidecar,
)
from videocreator.muse_gateway.store import (
    count_active_muse_tasks,
    create_muse_task,
    get_muse_task,
    list_muse_tasks,
    update_muse_task,
)
from videocreator.muse_gateway.storyboard import (
    assemble_storyboard,
    create_storyboard,
    delete_storyboard,
    get_storyboard,
    list_storyboards,
    regenerate_storyboard_segment,
    start_storyboard_generation,
    update_storyboard,
)
from videocreator.muse_gateway.studio_bridge import create_trend_motion_remix_task
from videocreator.paths import AppPaths
from videocreator.secrets_store import SecretsStore
from videocreator.timeutil import utc_now_iso

router = APIRouter()


def map_muse_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, MuseUnsafeGatewayError):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, MuseUnavailable):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, MuseAuthError):
        return HTTPException(
            status_code=502,
            detail=f"{exc} — Hãy bấm 'Kết nối 1 chạm' trong Cài đặt → Muse Gateway.",
        )
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, (MuseInputError, ValueError)):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, MuseGatewayError):
        return HTTPException(status_code=502, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


class MusePairBody(BaseModel):
    app_name: str = "Video Creator V2"


class MuseTaskCreateBody(BaseModel):
    workspace_id: int | None = None
    kind: str = "video"
    model: str | None = None
    purpose: str = "studio"
    prompt: str
    duration: int | None = 8
    ratio: str = "9:16"
    count: int | None = None
    voice: str | None = None
    language: str | None = None
    speed: float | None = None
    refs: list[dict[str, Any]] = Field(default_factory=list)
    variants: int = Field(default=1, ge=1, le=16)
    priority: int = 0
    parent_task_id: int | None = None
    ref_type: str | None = None
    ref_id: int | None = None


class MuseTaskContinueBody(BaseModel):
    prompt: str
    duration: int | None = None
    ratio: str | None = None


class MuseTrendRemixBody(BaseModel):
    workspace_id: int | None = None
    prompt: str = ""
    rights_confirmed: bool = False
    duration_sec: int = 10
    ratio: str = "9:16"


class MuseStoryboardCreateBody(BaseModel):
    workspace_id: int | None = None
    title: str
    segments: list[dict[str, Any]]
    ratio: str = "9:16"
    model: str | None = None
    continuity: bool = True
    narration: dict[str, Any] = Field(default_factory=dict)
    style_preset: str = "tiktok_karaoke"
    shared_refs: list[dict[str, Any]] = Field(default_factory=list)


class MuseStoryboardPatchBody(BaseModel):
    title: str | None = None
    style_preset: str | None = None
    narration: dict[str, Any] | None = None


class MuseSegmentRegenBody(BaseModel):
    prompt: str | None = None


def _collect_muse_status(paths: AppPaths, workspace_id: int | None) -> dict[str, Any]:
    settings = load_settings(paths.config_file)
    cfg = settings.muse_gateway
    sec = SecretsStore(paths.secrets_file)
    paired = sec.has("MUSE_GATEWAY_API_KEY")
    sidecar_info = get_sidecar_runtime_status(paths)
    queue_counts = count_active_muse_tasks(paths.db_file, workspace_id=workspace_id)

    today_key = budget_day(paths.db_file)
    stats_row = query_one(
        paths.db_file,
        """
        SELECT
            SUM(CASE WHEN kind = 'video' AND status = 'succeeded' THEN 1 ELSE 0 END) AS ok_vids,
            SUM(CASE WHEN kind = 'video' AND status = 'failed' THEN 1 ELSE 0 END) AS fail_vids
        FROM muse_tasks
        WHERE substr(created_at, 1, 10) = ?
        """,
        (today_key,),
    ) or {}
    ok_today = int(stats_row.get("ok_vids") or 0)
    fail_today = int(stats_row.get("fail_vids") or 0)
    denom = ok_today + fail_today
    success_rate = round((ok_today / denom) * 100.0, 1) if denom > 0 else 100.0

    online = False
    hardened = False
    version = ""
    unsafe_error = sidecar_info.get("unsafe_error") or ""
    accounts_summary = {"total": 0, "ready": 0, "busy": 0, "cooldown": 0}
    capacity = 0

    try:
        client = MuseGatewayClient(cfg, sec, timeout_s=4.0)
        safety = client.verify_ready_and_safe()
        online = True
        hardened = bool(safety.get("hardened"))
        disc = client.discover()
        version = str(disc.get("version") or "")
        pool_state: dict[str, Any] | None = None
        if cfg.mode == "local_sidecar":
            try:
                pool_state = get_muse_pool(paths)
                for acc in pool_state.get("accounts") or []:
                    st = str(acc.get("status") or "ready")
                    accounts_summary["total"] += 1
                    if st == "ready" and acc.get("enabled", True):
                        accounts_summary["ready"] += 1
                    elif st in ("busy", "queued"):
                        accounts_summary["busy"] += 1
                    elif st == "cooldown":
                        accounts_summary["cooldown"] += 1
            except MuseGatewayError:
                pool_state = None
        cap_info = compute_gateway_capacity(pool_state, cfg, discover_info=disc)
        capacity = int(cap_info["capacity"])
        if accounts_summary["total"] == 0:
            accounts_summary["total"] = int(cap_info["total_accounts"])
            accounts_summary["ready"] = int(cap_info["eligible_accounts"])
            accounts_summary["cooldown"] = int(cap_info["cooling_accounts"])
    except MuseUnsafeGatewayError as exc:
        unsafe_error = str(exc)
    except MuseGatewayError:
        pass

    return {
        "enabled": cfg.enabled,
        "mode": cfg.mode,
        "base_url": cfg.base_url,
        "paired": paired,
        "online": online,
        "hardened": hardened,
        "unsafe_error": unsafe_error,
        "version": version,
        "sidecar": sidecar_info,
        "accounts": accounts_summary,
        "capacity": capacity,
        "queue": queue_counts,
        "today": {
            "videos_succeeded": ok_today,
            "videos_failed": fail_today,
            "success_rate": success_rate,
        },
    }


@router.get("/muse/status")
async def api_v1_muse_status(
    request: Request, workspace_id: int | None = Query(default=None)
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    ws_id = resolve_workspace_id(paths.db_file, workspace_id) if workspace_id else None
    payload = await asyncio.to_thread(_collect_muse_status, paths, ws_id)
    return JSONResponse(payload)


@router.post("/muse/pair")
async def api_v1_muse_pair_start(request: Request, body: MusePairBody | None = None) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    payload = body or MusePairBody()
    try:
        res = await asyncio.to_thread(start_gateway_pairing, paths, app_name=payload.app_name)
        return JSONResponse(res)
    except Exception as exc:
        raise map_muse_http_error(exc) from exc


@router.get("/muse/pair/{pair_id}")
async def api_v1_muse_pair_poll(request: Request, pair_id: str) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    try:
        res = await asyncio.to_thread(poll_gateway_pairing, paths, pair_id)
        return JSONResponse(res)
    except Exception as exc:
        raise map_muse_http_error(exc) from exc


@router.post("/muse/sidecar/start")
async def api_v1_muse_sidecar_start(request: Request) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    try:
        res = await asyncio.to_thread(ensure_muse_sidecar_running, paths)
        return JSONResponse(res)
    except Exception as exc:
        raise map_muse_http_error(exc) from exc


@router.post("/muse/sidecar/stop")
async def api_v1_muse_sidecar_stop(request: Request) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    stopped = await asyncio.to_thread(stop_muse_sidecar, paths, only_if_owned=False)
    return JSONResponse({"stopped": stopped, "sidecar": get_sidecar_runtime_status(paths)})


@router.get("/muse/models")
async def api_v1_muse_models(request: Request) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    cfg = load_settings(paths.config_file).muse_gateway
    sec = SecretsStore(paths.secrets_file)

    def _load() -> dict[str, Any]:
        client = MuseGatewayClient(cfg, sec)
        client.verify_ready_and_safe()
        models = client.list_models()
        combos = list_muse_combos(paths) if cfg.mode == "local_sidecar" else []
        return {"models": models, "combos": combos}

    try:
        return JSONResponse(await asyncio.to_thread(_load))
    except Exception as exc:
        raise map_muse_http_error(exc) from exc


@router.get("/muse/tasks")
async def api_v1_muse_list_tasks(
    request: Request,
    workspace_id: int | None = Query(default=None),
    status: str | None = Query(default=None),
    purpose: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=300),
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    ws_id = resolve_workspace_id(paths.db_file, workspace_id) if workspace_id else None
    rows = list_muse_tasks(
        paths.db_file, workspace_id=ws_id, status=status, purpose=purpose, limit=limit
    )
    return JSONResponse({"tasks": rows, "queue": count_active_muse_tasks(paths.db_file, workspace_id=ws_id)})


@router.post("/muse/tasks", status_code=201)
async def api_v1_muse_create_task(request: Request, body: MuseTaskCreateBody) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    ws_id = resolve_workspace_id(paths.db_file, body.workspace_id)
    cfg = load_settings(paths.config_file).muse_gateway
    if body.kind not in ("video", "image", "audio", "chat"):
        raise HTTPException(status_code=400, detail=f"Unsupported muse task kind '{body.kind}'")

    try:
        if body.refs:
            validate_muse_refs_policy(paths, workspace_id=ws_id, refs=body.refs, actor="api")
    except Exception as exc:
        raise map_muse_http_error(exc) from exc

    default_model_map = {
        "video": cfg.default_video_model or "muse-video",
        "image": cfg.default_image_model or "muse-image",
        "audio": "muse-voice",
        "chat": "muse-chat",
    }
    chosen_model = (body.model or default_model_map[body.kind]).strip()
    params: dict[str, Any] = {}
    if body.kind == "video":
        params["duration"] = max(1, min(60, int(body.duration or 8)))
        params["ratio"] = body.ratio
    elif body.kind == "image":
        params["ratio"] = body.ratio
        params["count"] = max(1, min(4, int(body.count or 1)))
    elif body.kind == "audio":
        params["voice"] = body.voice or cfg.default_voice
        if body.language:
            params["language"] = body.language
        if body.speed is not None:
            params["speed"] = body.speed

    thread_url: str | None = None
    account_id: str | None = None
    if body.parent_task_id:
        parent = get_muse_task(paths.db_file, body.parent_task_id)
        if parent is None:
            raise HTTPException(status_code=404, detail=f"Parent task #{body.parent_task_id} not found")
        thread_url = parent.get("thread_url")
        account_id = parent.get("account_id")

    purpose = "variant" if body.variants > 1 and body.purpose == "studio" else body.purpose
    created_rows: list[dict[str, Any]] = []
    try:
        for _ in range(int(body.variants)):
            created_rows.append(
                create_muse_task(
                    paths.db_file,
                    workspace_id=ws_id,
                    kind=body.kind,
                    model=chosen_model,
                    purpose=purpose,
                    prompt=body.prompt,
                    params=params,
                    refs=body.refs,
                    ref_type=body.ref_type,
                    ref_id=body.ref_id,
                    thread_url=thread_url,
                    account_id=account_id,
                    parent_task_id=body.parent_task_id,
                    priority=body.priority,
                )
            )
    except Exception as exc:
        raise map_muse_http_error(exc) from exc

    return JSONResponse({"task": created_rows[0], "tasks": created_rows}, status_code=201)


@router.get("/muse/tasks/{task_id}")
async def api_v1_muse_get_task(request: Request, task_id: int) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    row = get_muse_task(paths.db_file, task_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Muse task #{task_id} not found")
    return JSONResponse({"task": row})


@router.post("/muse/tasks/{task_id}/cancel")
async def api_v1_muse_cancel_task(request: Request, task_id: int) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    row = get_muse_task(paths.db_file, task_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Muse task #{task_id} not found")

    warning = ""
    if row["status"] == "submitted" and row.get("gateway_task_id"):
        warning = "Muse có thể vẫn đang render trên trình duyệt và tiêu tốn hạn mức tài khoản."
        cfg = load_settings(paths.config_file).muse_gateway
        sec = SecretsStore(paths.secrets_file)

        def _cancel_remote() -> None:
            try:
                MuseGatewayClient(cfg, sec).cancel_task(str(row["gateway_task_id"]))
            except MuseGatewayError:
                pass

        await asyncio.to_thread(_cancel_remote)

    updated = update_muse_task(
        paths.db_file, task_id, status="cancelled", finished_at=utc_now_iso()
    )
    return JSONResponse({"task": updated, "warning": warning})


@router.post("/muse/tasks/{task_id}/retry")
async def api_v1_muse_retry_task(request: Request, task_id: int) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    row = get_muse_task(paths.db_file, task_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Muse task #{task_id} not found")
    updated = update_muse_task(
        paths.db_file,
        task_id,
        status="pending",
        attempt=int(row.get("attempt") or 0) + 1,
        gateway_task_id=None,
        idempotency_key=None,
        error=None,
        retry_after=None,
        finished_at=None,
    )
    return JSONResponse({"task": updated})


@router.post("/muse/tasks/{task_id}/continue", status_code=201)
async def api_v1_muse_continue_task(
    request: Request, task_id: int, body: MuseTaskContinueBody
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    parent = get_muse_task(paths.db_file, task_id)
    if parent is None:
        raise HTTPException(status_code=404, detail=f"Muse task #{task_id} not found")
    if not parent.get("thread_url") or not parent.get("account_id"):
        raise HTTPException(
            status_code=400,
            detail="Task gốc không có thread_url/account_id để 'Sửa tiếp' trên cùng hội thoại.",
        )
    prev_params = dict(parent.get("params") or {})
    params = {
        **prev_params,
        "new_chat": False,
        "duration": int(body.duration or prev_params.get("duration") or 8),
        "ratio": str(body.ratio or prev_params.get("ratio") or "9:16"),
    }
    child = create_muse_task(
        paths.db_file,
        workspace_id=int(parent["workspace_id"]),
        kind=str(parent["kind"]),
        model=str(parent["model"]),
        purpose="studio",
        prompt=body.prompt,
        params=params,
        thread_url=str(parent["thread_url"]),
        account_id=str(parent["account_id"]),
        parent_task_id=task_id,
        priority=int(parent.get("priority") or 0),
    )
    return JSONResponse({"task": child}, status_code=201)


@router.post("/muse/tasks/{task_id}/import")
async def api_v1_muse_import_task(request: Request, task_id: int) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    row = get_muse_task(paths.db_file, task_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Muse task #{task_id} not found")
    if row.get("shot_id") or row.get("ai_image_id") or row.get("asset_id"):
        return JSONResponse({"task": row, "already_imported": True})
    if not row.get("gateway_task_id"):
        raise HTTPException(status_code=400, detail="Task chưa có gateway_task_id để tải media")

    def _run_import() -> dict[str, Any]:
        cfg = load_settings(paths.config_file).muse_gateway
        client = MuseGatewayClient(cfg, SecretsStore(paths.secrets_file))
        remote = client.get_task(str(row["gateway_task_id"]))
        return import_completed_muse_task(paths, client, row, remote)

    try:
        done = await asyncio.to_thread(_run_import)
        return JSONResponse({"task": done, "already_imported": False})
    except Exception as exc:
        raise map_muse_http_error(exc) from exc


@router.post("/muse/dispatch")
async def api_v1_muse_dispatch_now(request: Request) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    res = await asyncio.to_thread(run_muse_dispatcher_tick, paths)
    return JSONResponse(res)


@router.post("/muse/refs/upload", status_code=201)
async def api_v1_muse_upload_ref(
    request: Request,
    file: UploadFile = File(...),
    workspace_id: int | None = Form(default=None),
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    ws_id = resolve_workspace_id(paths.db_file, workspace_id)
    raw = await file.read()
    try:
        res = await asyncio.to_thread(
            stage_uploaded_muse_ref,
            paths,
            filename=file.filename,
            data=raw,
            workspace_id=ws_id,
        )
        return JSONResponse(res, status_code=201)
    except Exception as exc:
        raise map_muse_http_error(exc) from exc


@router.post("/muse/trends/{trend_id}/remix", status_code=201)
async def api_v1_muse_trend_remix(
    request: Request, trend_id: int, body: MuseTrendRemixBody
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    ws_id = resolve_workspace_id(paths.db_file, body.workspace_id)
    try:
        task = await asyncio.to_thread(
            create_trend_motion_remix_task,
            paths,
            workspace_id=ws_id,
            trend_id=trend_id,
            prompt=body.prompt,
            rights_confirmed=body.rights_confirmed,
            duration_sec=body.duration_sec,
            ratio=body.ratio,
        )
        return JSONResponse({"task": task}, status_code=201)
    except Exception as exc:
        raise map_muse_http_error(exc) from exc


@router.get("/muse/storyboards")
async def api_v1_muse_list_storyboards(
    request: Request, workspace_id: int | None = Query(default=None)
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    ws_id = resolve_workspace_id(paths.db_file, workspace_id)
    return JSONResponse({"storyboards": list_storyboards(paths.db_file, workspace_id=ws_id)})


@router.post("/muse/storyboards", status_code=201)
async def api_v1_muse_create_storyboard(
    request: Request, body: MuseStoryboardCreateBody
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    ws_id = resolve_workspace_id(paths.db_file, body.workspace_id)
    try:
        sb = create_storyboard(
            paths,
            workspace_id=ws_id,
            title=body.title,
            segments=body.segments,
            ratio=body.ratio,
            model=body.model,
            continuity=body.continuity,
            narration=body.narration,
            style_preset=body.style_preset,
            shared_refs=body.shared_refs,
        )
        return JSONResponse({"storyboard": sb}, status_code=201)
    except Exception as exc:
        raise map_muse_http_error(exc) from exc


@router.get("/muse/storyboards/{sb_id}")
async def api_v1_muse_get_storyboard(request: Request, sb_id: int) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    sb = get_storyboard(paths.db_file, sb_id)
    if sb is None:
        raise HTTPException(status_code=404, detail=f"Storyboard #{sb_id} not found")
    return JSONResponse({"storyboard": sb})


@router.patch("/muse/storyboards/{sb_id}")
async def api_v1_muse_patch_storyboard(
    request: Request, sb_id: int, body: MuseStoryboardPatchBody
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    sb = update_storyboard(
        paths, sb_id, title=body.title, style_preset=body.style_preset, narration=body.narration
    )
    if sb is None:
        raise HTTPException(status_code=404, detail=f"Storyboard #{sb_id} not found")
    return JSONResponse({"storyboard": sb})


@router.delete("/muse/storyboards/{sb_id}")
async def api_v1_muse_delete_storyboard(request: Request, sb_id: int) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    if not delete_storyboard(paths.db_file, sb_id):
        raise HTTPException(status_code=404, detail=f"Storyboard #{sb_id} not found")
    return JSONResponse({"deleted": True})


@router.post("/muse/storyboards/{sb_id}/generate")
async def api_v1_muse_generate_storyboard(request: Request, sb_id: int) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    try:
        sb = await asyncio.to_thread(start_storyboard_generation, paths, sb_id)
        return JSONResponse({"storyboard": sb})
    except Exception as exc:
        raise map_muse_http_error(exc) from exc


@router.post("/muse/storyboards/{sb_id}/assemble")
async def api_v1_muse_assemble_storyboard(request: Request, sb_id: int) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    try:
        sb = await asyncio.to_thread(assemble_storyboard, paths, sb_id)
        return JSONResponse({"storyboard": sb})
    except Exception as exc:
        raise map_muse_http_error(exc) from exc


@router.post("/muse/storyboards/{sb_id}/segments/{seg_idx}/regenerate")
async def api_v1_muse_regen_storyboard_segment(
    request: Request, sb_id: int, seg_idx: int, body: MuseSegmentRegenBody | None = None
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    payload = body or MuseSegmentRegenBody()
    try:
        sb = await asyncio.to_thread(
            regenerate_storyboard_segment, paths, sb_id, seg_idx, prompt=payload.prompt
        )
        return JSONResponse({"storyboard": sb})
    except Exception as exc:
        raise map_muse_http_error(exc) from exc

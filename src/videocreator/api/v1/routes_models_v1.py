"""On-demand Local AI Models Manager & Multi-Key Rotation Pool endpoints for `/api/v1`."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from videocreator.ai.key_pool import (
    add_pooled_key,
    delete_pooled_key,
    list_pooled_keys,
    update_pooled_key,
)
from videocreator.jobs import enqueue_job
from videocreator.models_manager import (
    get_local_model,
    install_local_model,
    list_local_models,
    remove_local_model,
)
from videocreator.paths import AppPaths

router = APIRouter()


class ModelInstallBody(BaseModel):
    local_source_path: str | None = None
    expected_sha256: str | None = None
    sync: bool = False


class KeyPoolCreateBody(BaseModel):
    provider: str
    raw_secret: str
    label: str = ""
    priority: int = 0


class KeyPoolPatchBody(BaseModel):
    label: str | None = None
    enabled: bool | None = None
    priority: int | None = None
    clear_cooldown: bool = False


@router.get("/models")
async def api_v1_list_models(request: Request) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    return JSONResponse(
        {
            "models": list_local_models(paths),
            "models_dir": str(paths.models_dir),
        }
    )


@router.post("/models/{model_id}/install")
async def api_v1_install_model(
    request: Request,
    model_id: str,
    body: ModelInstallBody | None = None,
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    info = get_local_model(paths, model_id)
    if info is None:
        raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found")
    payload = body or ModelInstallBody()
    if payload.local_source_path or payload.sync:
        try:
            model = install_local_model(
                paths,
                model_id,
                local_source_path=payload.local_source_path,
                expected_sha256=payload.expected_sha256,
            )
            return JSONResponse({"model": model, "job_id": None})
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    job_id = enqueue_job(
        paths.db_file,
        "download_model",
        ref_id=int(info["rowid"]),
        lane="io",
    )
    return JSONResponse({"model": info, "job_id": job_id}, status_code=202)


@router.delete("/models/{model_id}")
async def api_v1_delete_model(request: Request, model_id: str) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    try:
        model = remove_local_model(paths, model_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return JSONResponse({"model": model})


@router.get("/key-pool")
async def api_v1_list_key_pool(
    request: Request,
    provider: str | None = Query(default=None),
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    return JSONResponse({"keys": list_pooled_keys(paths, provider=provider)})


@router.post("/key-pool", status_code=201)
async def api_v1_add_key_pool(
    request: Request, body: KeyPoolCreateBody
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    try:
        item = add_pooled_key(
            paths,
            provider=body.provider,
            raw_secret=body.raw_secret,
            label=body.label,
            priority=body.priority,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse({"key": item}, status_code=201)


@router.patch("/key-pool/{key_id}")
async def api_v1_patch_key_pool(
    request: Request, key_id: int, body: KeyPoolPatchBody
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    item = update_pooled_key(
        paths,
        key_id,
        label=body.label,
        enabled=body.enabled,
        priority=body.priority,
        clear_cooldown=body.clear_cooldown,
    )
    if item is None:
        raise HTTPException(status_code=404, detail=f"Pooled key #{key_id} not found")
    return JSONResponse({"key": item})


@router.delete("/key-pool/{key_id}")
async def api_v1_delete_key_pool(request: Request, key_id: int) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    if not delete_pooled_key(paths, key_id):
        raise HTTPException(status_code=404, detail=f"Pooled key #{key_id} not found")
    return JSONResponse({"ok": True, "deleted_id": key_id})

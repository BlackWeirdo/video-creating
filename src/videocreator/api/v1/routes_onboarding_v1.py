"""Welcome Wizard onboarding and Encrypted `.vcx` Backup/Restore endpoints (`/api/v1`)."""
from __future__ import annotations

import asyncio
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from videocreator.config import load_settings
from videocreator.onboarding import (
    complete_onboarding,
    get_backup_summary,
    get_onboarding_status,
    reset_onboarding,
)
from videocreator.paths import AppPaths
from videocreator.transfer import (
    ExportPasswordError,
    export_config_bundle,
    import_config_bundle,
)

router = APIRouter()
MAX_IMPORT_VCX_BYTES = 512 * 1024 * 1024


class OnboardingCompleteBody(BaseModel):
    workspace: dict[str, Any] | None = None
    daily_usd: float | None = None
    api_fallback: str | None = None
    timezone: str | None = None
    vi_provider: str | None = None
    vi_voice: str | None = None
    secrets: dict[str, str] = Field(default_factory=dict)
    pooled_keys: list[dict[str, Any]] = Field(default_factory=list)


class BackupExportBody(BaseModel):
    password: str
    save_copy: bool = True


@router.get("/onboarding/status")
async def api_v1_onboarding_status(request: Request) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    return JSONResponse(
        get_onboarding_status(paths, secrets_store=request.app.state.secrets)
    )


@router.post("/onboarding/complete")
async def api_v1_onboarding_complete(
    request: Request, body: OnboardingCompleteBody
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    try:
        status = complete_onboarding(
            paths,
            body.model_dump(exclude_none=True),
            secrets_store=request.app.state.secrets,
        )
    except (ValueError, LookupError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(status)


@router.post("/onboarding/reset")
async def api_v1_onboarding_reset(request: Request) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    return JSONResponse(
        reset_onboarding(paths, secrets_store=request.app.state.secrets)
    )


@router.get("/backup/summary")
async def api_v1_backup_summary(request: Request) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    return JSONResponse(
        get_backup_summary(paths, secrets_store=request.app.state.secrets)
    )


@router.post("/backup/export")
async def api_v1_backup_export(
    request: Request, body: BackupExportBody
) -> FileResponse:
    paths: AppPaths = request.app.state.paths
    dest_vcx = paths.work_dir / f"videocreator-v2-export-{uuid.uuid4().hex}.vcx"
    try:
        await asyncio.to_thread(
            export_config_bundle,
            paths,
            body.password,
            dest_vcx,
            secrets_store=request.app.state.secrets,
        )
        if body.save_copy:
            paths.backups_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            shutil.copy2(dest_vcx, paths.backups_dir / f"backup-{stamp}.vcx")
    except ExportPasswordError as exc:
        dest_vcx.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return FileResponse(
        dest_vcx,
        media_type="application/octet-stream",
        filename="videocreator-v2-backup.vcx",
        background=BackgroundTask(dest_vcx.unlink, missing_ok=True),
    )


@router.post("/backup/restore")
async def api_v1_backup_restore(
    request: Request,
    file: UploadFile = File(...),
    password: str = Form(...),
    as_server: bool = Form(True),
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    tmp_vcx = paths.work_dir / f"videocreator-v2-import-{uuid.uuid4().hex}.vcx"
    pre_restore_vcx: Path | None = None
    try:
        written = 0
        with tmp_vcx.open("wb") as out_f:
            while chunk := await file.read(1024 * 1024):
                written += len(chunk)
                if written > MAX_IMPORT_VCX_BYTES:
                    raise HTTPException(
                        status_code=413, detail="File sao lưu (.vcx) vượt quá 512 MB"
                    )
                out_f.write(chunk)

        if paths.db_file.is_file() and len(password.strip()) >= 4:
            paths.backups_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
            pre_restore_vcx = paths.backups_dir / f"pre-restore-{stamp}.vcx"
            await asyncio.to_thread(
                export_config_bundle,
                paths,
                password,
                pre_restore_vcx,
                secrets_store=request.app.state.secrets,
            )

        worker = getattr(request.app.state, "worker", None)
        was_paused = bool(worker.is_paused) if worker is not None else False
        if worker is not None and not was_paused:
            worker.pause()
            await worker.wait_until_idle(timeout_s=10.0)

        try:
            await asyncio.to_thread(
                import_config_bundle,
                paths,
                tmp_vcx,
                password,
                as_server=as_server,
                secrets_store=request.app.state.secrets,
            )
        except Exception:
            if worker is not None and not was_paused:
                worker.resume()
            raise
        new_role = load_settings(paths.config_file).role
        if new_role == "client":
            for svc_attr in ("scheduler", "tg_service", "worker"):
                svc = getattr(request.app.state, svc_attr, None)
                if svc is not None:
                    stop_fn = getattr(svc, "stop", None)
                    if callable(stop_fn):
                        res = stop_fn()
                        if asyncio.iscoroutine(res):
                            await res
    except (ExportPasswordError, ValueError) as exc:
        if pre_restore_vcx is not None:
            pre_restore_vcx.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        tmp_vcx.unlink(missing_ok=True)

    return JSONResponse(
        {
            "restored": True,
            "role": load_settings(paths.config_file).role,
            "pre_restore_backup": pre_restore_vcx.name if pre_restore_vcx and pre_restore_vcx.is_file() else "",
            "summary": get_backup_summary(paths, secrets_store=request.app.state.secrets),
            "onboarding": get_onboarding_status(paths, secrets_store=request.app.state.secrets),
        }
    )

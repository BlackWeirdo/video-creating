"""Export and import of the encrypted configuration bundle (`.vcx`)."""
from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from starlette.background import BackgroundTask

from videocreator.config import load_settings
from videocreator.paths import AppPaths
from videocreator.transfer import ExportPasswordError, export_config_bundle, import_config_bundle

router = APIRouter()
MAX_IMPORT_VCX_BYTES = 512 * 1024 * 1024


@router.post("/settings/export")
async def export_settings_route(request: Request, password: str = Form(...)) -> FileResponse:
    paths: AppPaths = request.app.state.paths
    dest_vcx = paths.work_dir / f"videocreator-export-{uuid.uuid4().hex}.vcx"
    try:
        await asyncio.to_thread(export_config_bundle, paths, password, dest_vcx, secrets_store=request.app.state.secrets)
    except ExportPasswordError as exc:
        dest_vcx.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return FileResponse(
        dest_vcx,
        media_type="application/octet-stream",
        filename="videocreator-export.vcx",
        background=BackgroundTask(dest_vcx.unlink, missing_ok=True),
    )


@router.post("/settings/import")
async def import_settings_route(
    request: Request,
    file: UploadFile = File(...),
    password: str = Form(...),
    as_server: bool = Form(False),
) -> RedirectResponse:
    paths: AppPaths = request.app.state.paths
    tmp_vcx = paths.work_dir / f"videocreator-import-{uuid.uuid4().hex}.vcx"
    try:
        written = 0
        with tmp_vcx.open("wb") as out_f:
            while chunk := await file.read(1024 * 1024):
                written += len(chunk)
                if written > MAX_IMPORT_VCX_BYTES:
                    raise HTTPException(status_code=413, detail="File cấu hình (.vcx) vượt quá giới hạn 512 MB")
                out_f.write(chunk)
        await asyncio.to_thread(
            import_config_bundle,
            paths,
            tmp_vcx,
            password,
            as_server=as_server,
            secrets_store=request.app.state.secrets,
        )
        # If imported as client on an active server, stop background server workers to prevent split-brain
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
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        tmp_vcx.unlink(missing_ok=True)
    return RedirectResponse(url="/settings?saved=imported", status_code=303)

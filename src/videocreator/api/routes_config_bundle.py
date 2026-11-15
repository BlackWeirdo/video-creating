"""Export and import of the encrypted configuration bundle (`.vcx`)."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse

from videocreator.paths import AppPaths
from videocreator.transfer import ExportPasswordError, export_config_bundle, import_config_bundle

router = APIRouter()


@router.post("/settings/export")
async def export_settings_route(request: Request, password: str = Form(...)) -> FileResponse:
    paths: AppPaths = request.app.state.paths
    dest_vcx = paths.work_dir / "videocreator-export.vcx"
    try:
        await asyncio.to_thread(export_config_bundle, paths, password, dest_vcx, secrets_store=request.app.state.secrets)
    except ExportPasswordError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return FileResponse(
        dest_vcx,
        media_type="application/octet-stream",
        filename="videocreator-export.vcx",
    )


@router.post("/settings/import")
async def import_settings_route(
    request: Request,
    file: UploadFile = File(...),
    password: str = Form(...),
    as_server: bool = Form(False),
) -> RedirectResponse:
    paths: AppPaths = request.app.state.paths
    tmp_vcx = paths.work_dir / "videocreator-import.vcx"
    try:
        with tmp_vcx.open("wb") as out_f:
            while chunk := await file.read(1024 * 1024):
                out_f.write(chunk)
        await asyncio.to_thread(
            import_config_bundle,
            paths,
            tmp_vcx,
            password,
            as_server=as_server,
            secrets_store=request.app.state.secrets,
        )
    except (ExportPasswordError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        tmp_vcx.unlink(missing_ok=True)
    return RedirectResponse(url="/settings?saved=imported", status_code=303)

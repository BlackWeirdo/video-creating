"""Workspace-scoped Assets (Music, SFX, B-roll) endpoints for `/api/v1`."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from videocreator.api.v1.deps import resolve_workspace_id
from videocreator.api.v1.uploads import save_upload_to_temp
from videocreator.db import get_conn, query_all, query_one, record_audit
from videocreator.db_rows import file_media_url
from videocreator.jsonutil import loads_or
from videocreator.paths import AppPaths
from videocreator.services.assets import (
    ALLOWED_AUDIO_EXTENSIONS,
    MAX_AUDIO_UPLOAD_BYTES,
    import_audio_asset,
)

router = APIRouter()


class LocalAssetImportBody(BaseModel):
    source_path: str
    workspace_id: int | None = None
    kind: Literal["music", "sfx"] = "music"
    title: str = ""


def serialize_asset(row: dict[str, Any]) -> dict[str, Any]:
    meta = loads_or(row.get("meta_json"), {})
    if not isinstance(meta, dict):
        meta = {}
    rel = str(row.get("path") or "")
    return {
        "id": int(row["id"]),
        "workspace_id": int(row.get("workspace_id") or 1),
        "kind": str(row.get("kind") or "music"),
        "path": rel,
        "media_url": file_media_url(rel, empty=None),
        "duration_s": float(row.get("duration_s") or 0.0),
        "title": str(meta.get("title") or rel),
        "meta": meta,
        "created_at": str(row.get("created_at") or ""),
    }


@router.get("/assets")
async def api_v1_list_assets(
    request: Request,
    workspace_id: int | None = Query(default=None),
    kind: str | None = Query(default=None),
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    ws_id = resolve_workspace_id(paths.db_file, workspace_id)
    sql = "SELECT * FROM assets WHERE workspace_id = ?"
    params: list[Any] = [ws_id]
    if kind:
        sql += " AND kind = ?"
        params.append(kind.strip())
    sql += " ORDER BY id DESC"
    rows = query_all(paths.db_file, sql, params)
    return JSONResponse({"assets": [serialize_asset(r) for r in rows], "workspace_id": ws_id})


@router.post("/assets/upload", status_code=201)
async def api_v1_upload_asset(
    request: Request,
    file: UploadFile = File(...),
    workspace_id: int | None = Form(default=None),
    kind: Literal["music", "sfx"] = Form(default="music"),
    title: str = Form(default=""),
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    ws_id = resolve_workspace_id(paths.db_file, workspace_id, require_active=True)
    tmp_path = await save_upload_to_temp(
        file,
        paths.work_dir,
        allowed_extensions=ALLOWED_AUDIO_EXTENSIONS,
        default_ext=".wav",
        max_bytes=MAX_AUDIO_UPLOAD_BYTES,
        prefix="asset_up",
    )
    try:
        aid = await asyncio.to_thread(
            import_audio_asset,
            paths,
            tmp_path,
            kind=kind,
            title=title or Path(file.filename or "audio").stem,
            workspace_id=ws_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        tmp_path.unlink(missing_ok=True)
    row = query_one(paths.db_file, "SELECT * FROM assets WHERE id = ?", (aid,))
    assert row is not None
    return JSONResponse({"asset": serialize_asset(row)}, status_code=201)


@router.post("/assets/import-local", status_code=201)
async def api_v1_import_local_asset(
    request: Request, body: LocalAssetImportBody
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    ws_id = resolve_workspace_id(paths.db_file, body.workspace_id, require_active=True)
    src = Path(body.source_path.strip())
    if not src.exists() or not src.is_file():
        raise HTTPException(status_code=400, detail=f"File not found: {src}")
    try:
        aid = await asyncio.to_thread(
            import_audio_asset,
            paths,
            src,
            kind=body.kind,
            title=body.title,
            workspace_id=ws_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    row = query_one(paths.db_file, "SELECT * FROM assets WHERE id = ?", (aid,))
    assert row is not None
    return JSONResponse({"asset": serialize_asset(row)}, status_code=201)


@router.delete("/assets/{asset_id}")
async def api_v1_delete_asset(request: Request, asset_id: int) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    row = query_one(paths.db_file, "SELECT id, path FROM assets WHERE id = ?", (asset_id,))
    if row is None:
        raise HTTPException(status_code=404, detail=f"Asset #{asset_id} not found")
    with get_conn(paths.db_file) as conn:
        conn.execute("DELETE FROM assets WHERE id = ?", (asset_id,))
        record_audit(
            conn,
            actor="api",
            action="asset.deleted",
            object_type="asset",
            object_id=asset_id,
            detail=str(row.get("path") or ""),
        )
    return JSONResponse({"deleted": True, "asset_id": asset_id})

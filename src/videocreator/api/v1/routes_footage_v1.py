"""Workspace-scoped Footage & Shots endpoints for `/api/v1`."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from videocreator.api.v1.deps import resolve_workspace_id
from videocreator.api.v1.uploads import MAX_FOOTAGE_UPLOAD_BYTES, save_upload_to_temp
from videocreator.db import get_conn, query_all, query_one, record_audit
from videocreator.db_rows import file_media_url
from videocreator.jsonutil import loads_or, parse_int_list, parse_str_list
from videocreator.paths import AppPaths
from videocreator.pipeline.footage_import import ALLOWED_VIDEO_EXTENSIONS, import_footage_file
from videocreator.products import product_name_map

router = APIRouter()


class LocalFootageImportBody(BaseModel):
    source_path: str
    workspace_id: int | None = None
    product_ids: list[int] = Field(default_factory=list)
    no_product: bool = False
    enqueue_analysis: bool = True


class ShotUpdateBody(BaseModel):
    description: str | None = None
    tags: list[str] | None = None
    has_product: bool | None = None
    product_ids: list[int] | None = None
    quality: int | None = Field(default=None, ge=1, le=5)
    focus_x: float | None = Field(default=None, ge=0.0, le=1.0)


def serialize_footage_row(row: dict[str, Any], product_map: dict[int, str]) -> dict[str, Any]:
    pids = parse_int_list(row.get("product_ids_json"))
    rel = str(row.get("path") or "")
    return {
        "id": int(row["id"]),
        "workspace_id": int(row.get("workspace_id") or 1),
        "path": rel,
        "media_url": file_media_url(rel, empty=None),
        "sha256": str(row.get("sha256") or ""),
        "duration_s": float(row.get("duration_s") or 0.0),
        "width": int(row.get("width") or 0),
        "height": int(row.get("height") or 0),
        "orientation": str(row.get("orientation") or "portrait"),
        "crop": loads_or(row.get("crop_json"), None),
        "product_ids": pids,
        "product_names": [product_map.get(pid, f"#{pid}") for pid in pids],
        "status": str(row.get("status") or "imported"),
        "error": row.get("error"),
        "created_at": str(row.get("created_at") or ""),
    }


def serialize_shot_row(row: dict[str, Any], pmap: dict[int, str]) -> dict[str, Any]:
    pids = parse_int_list(row.get("product_ids_json"))
    tags = parse_str_list(row.get("tags_json"))
    src_rel = str(row.get("footage_path") or row.get("asset_path") or "")
    thumb_rel = str(row.get("thumb_path") or "")
    return {
        "id": int(row["id"]),
        "footage_id": row.get("footage_id"),
        "asset_id": row.get("asset_id"),
        "workspace_id": int(row.get("ws_id") or 1),
        "idx": int(row.get("idx") or 0),
        "start_s": float(row.get("start_s") or 0.0),
        "end_s": float(row.get("end_s") or 0.0),
        "duration_s": round(float(row.get("end_s") or 0.0) - float(row.get("start_s") or 0.0), 2),
        "description": str(row.get("description") or ""),
        "tags": tags,
        "has_product": bool(row.get("has_product")),
        "product_ids": pids,
        "product_names": [pmap.get(pid, f"#{pid}") for pid in pids],
        "quality": int(row.get("quality") or 3),
        "focus_x": row.get("focus_x"),
        "media_url": file_media_url(src_rel, empty=None),
        "thumb_url": file_media_url(thumb_rel, empty=None),
    }


@router.get("/footage")
async def api_v1_list_footage(
    request: Request,
    workspace_id: int | None = Query(default=None),
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    ws_id = resolve_workspace_id(paths.db_file, workspace_id)
    pmap = product_name_map(paths.db_file, workspace_id=ws_id)
    rows = query_all(
        paths.db_file,
        "SELECT * FROM footage WHERE workspace_id = ? ORDER BY id DESC",
        (ws_id,),
    )
    return JSONResponse(
        {
            "footage": [serialize_footage_row(r, pmap) for r in rows],
            "workspace_id": ws_id,
        }
    )


@router.post("/footage/upload", status_code=201)
async def api_v1_upload_footage(
    request: Request,
    file: UploadFile = File(...),
    workspace_id: int | None = Form(default=None),
    product_ids: str = Form(default=""),
    no_product: bool = Form(default=False),
    enqueue_analysis: bool = Form(default=False),
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    ws_id = resolve_workspace_id(paths.db_file, workspace_id, require_active=True)
    parsed_pids = [
        int(tok.strip())
        for tok in product_ids.replace(";", ",").split(",")
        if tok.strip().isdigit()
    ]
    tmp_path = await save_upload_to_temp(
        file,
        paths.work_dir,
        allowed_extensions=ALLOWED_VIDEO_EXTENSIONS,
        default_ext=".mp4",
        max_bytes=MAX_FOOTAGE_UPLOAD_BYTES,
        prefix="upload",
    )
    try:
        fid = await asyncio.to_thread(
            import_footage_file,
            paths,
            tmp_path,
            product_ids=parsed_pids,
            no_product=no_product,
            enqueue_analysis=enqueue_analysis,
            workspace_id=ws_id,
            actor="api",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        tmp_path.unlink(missing_ok=True)

    row = query_one(paths.db_file, "SELECT * FROM footage WHERE id = ?", (fid,))
    assert row is not None
    return JSONResponse(
        {
            "footage": serialize_footage_row(
                row, product_name_map(paths.db_file, workspace_id=ws_id)
            )
        },
        status_code=201,
    )


@router.post("/footage/import-local", status_code=201)
async def api_v1_import_local_footage(
    request: Request, body: LocalFootageImportBody
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    ws_id = resolve_workspace_id(paths.db_file, body.workspace_id, require_active=True)
    src = Path(body.source_path.strip())
    try:
        fid = await asyncio.to_thread(
            import_footage_file,
            paths,
            src,
            product_ids=body.product_ids,
            no_product=body.no_product,
            enqueue_analysis=body.enqueue_analysis,
            workspace_id=ws_id,
            actor="api",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    row = query_one(paths.db_file, "SELECT * FROM footage WHERE id = ?", (fid,))
    assert row is not None
    return JSONResponse(
        {
            "footage": serialize_footage_row(
                row, product_name_map(paths.db_file, workspace_id=ws_id)
            )
        },
        status_code=201,
    )


@router.get("/shots")
async def api_v1_list_shots(
    request: Request,
    workspace_id: int | None = Query(default=None),
    footage_id: int | None = Query(default=None),
    product_id: int | None = Query(default=None),
    has_product: bool | None = Query(default=None),
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    ws_id = resolve_workspace_id(paths.db_file, workspace_id)
    pmap = product_name_map(paths.db_file, workspace_id=ws_id)

    sql = """
        SELECT s.*, f.path AS footage_path, a.path AS asset_path,
               COALESCE(f.workspace_id, a.workspace_id, 1) AS ws_id
        FROM shots s
        LEFT JOIN footage f ON s.footage_id = f.id
        LEFT JOIN assets a ON s.asset_id = a.id
        WHERE COALESCE(f.workspace_id, a.workspace_id, 1) = ?
    """
    params: list[Any] = [ws_id]
    if footage_id is not None:
        sql += " AND s.footage_id = ?"
        params.append(int(footage_id))
    if has_product is not None:
        sql += " AND s.has_product = ?"
        params.append(1 if has_product else 0)
    sql += " ORDER BY s.footage_id DESC, s.idx ASC, s.id ASC"

    rows = query_all(paths.db_file, sql, params)
    items: list[dict[str, Any]] = []
    for r in rows:
        item = serialize_shot_row(r, pmap)
        if product_id is not None and int(product_id) not in item["product_ids"]:
            continue
        items.append(item)
    return JSONResponse({"shots": items, "workspace_id": ws_id})


@router.patch("/shots/{shot_id}")
async def api_v1_update_shot(
    request: Request, shot_id: int, body: ShotUpdateBody
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    row = query_one(
        paths.db_file,
        """
        SELECT s.*, f.path AS footage_path, a.path AS asset_path,
               COALESCE(f.workspace_id, a.workspace_id, 1) AS ws_id
        FROM shots s
        LEFT JOIN footage f ON s.footage_id = f.id
        LEFT JOIN assets a ON s.asset_id = a.id
        WHERE s.id = ?
        """,
        (shot_id,),
    )
    if row is None:
        raise HTTPException(status_code=404, detail=f"Shot #{shot_id} not found")

    next_desc = (
        body.description.strip()
        if body.description is not None
        else str(row.get("description") or "")
    )
    next_tags = (
        [t.strip() for t in body.tags if t.strip()]
        if body.tags is not None
        else parse_str_list(row.get("tags_json"))
    )
    next_pids = (
        sorted({int(x) for x in body.product_ids if int(x) > 0})
        if body.product_ids is not None
        else parse_int_list(row.get("product_ids_json"))
    )
    if body.has_product is not None:
        next_has_prod = 1 if body.has_product else 0
    else:
        next_has_prod = 1 if next_pids else int(row.get("has_product") or 0)
    next_quality = int(body.quality) if body.quality is not None else int(row.get("quality") or 3)
    next_focus_x = (
        round(float(body.focus_x), 4) if body.focus_x is not None else row.get("focus_x")
    )

    with get_conn(paths.db_file) as conn:
        conn.execute(
            """
            UPDATE shots
            SET description = ?,
                tags_json = ?,
                has_product = ?,
                product_ids_json = ?,
                quality = ?,
                focus_x = ?
            WHERE id = ?
            """,
            (
                next_desc,
                json.dumps(next_tags, ensure_ascii=False),
                next_has_prod,
                json.dumps(next_pids),
                next_quality,
                next_focus_x,
                shot_id,
            ),
        )
        record_audit(
            conn,
            actor="api",
            action="shot.updated",
            object_type="shot",
            object_id=shot_id,
            detail=f"has_product={next_has_prod}, focus_x={next_focus_x}",
        )

    updated = query_one(
        paths.db_file,
        """
        SELECT s.*, f.path AS footage_path, a.path AS asset_path,
               COALESCE(f.workspace_id, a.workspace_id, 1) AS ws_id
        FROM shots s
        LEFT JOIN footage f ON s.footage_id = f.id
        LEFT JOIN assets a ON s.asset_id = a.id
        WHERE s.id = ?
        """,
        (shot_id,),
    )
    assert updated is not None
    ws_id = int(updated.get("ws_id") or 1)
    return JSONResponse(
        {
            "shot": serialize_shot_row(
                updated, product_name_map(paths.db_file, workspace_id=ws_id)
            )
        }
    )

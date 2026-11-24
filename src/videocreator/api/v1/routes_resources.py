"""Workspace-scoped resource endpoints for `/api/v1`: products, footage, shots, assets, voices."""
from __future__ import annotations

import asyncio
import json
import shutil
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from videocreator.api.routes_assets import ALLOWED_AUDIO_EXTENSIONS, import_audio_asset
from videocreator.api.routes_voices import AVAILABLE_VOICE_CATALOG
from videocreator.api.v1.deps import resolve_workspace_id
from videocreator.config import load_settings, save_settings
from videocreator.db import get_conn, query_all, query_one, record_audit
from videocreator.jsonutil import loads_or, parse_int_list, parse_str_list
from videocreator.paths import AppPaths
from videocreator.pipeline.footage_import import ALLOWED_VIDEO_EXTENSIONS, import_footage_file
from videocreator.products import (
    create_product,
    delete_or_hide_product,
    get_product,
    list_products,
    product_name_map,
    update_product,
)
from videocreator.tts import TTSUnavailableError, count_syllables, synthesize_speech_segments

router = APIRouter()


class ProductCreateBody(BaseModel):
    workspace_id: int | None = None
    name: str
    material: str = ""
    facts: dict[str, Any] = Field(default_factory=dict)


class ProductUpdateBody(BaseModel):
    name: str | None = None
    material: str | None = None
    facts: dict[str, Any] | None = None


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


class LocalAssetImportBody(BaseModel):
    source_path: str
    workspace_id: int | None = None
    kind: Literal["music", "sfx"] = "music"
    title: str = ""


class VoicesUpdateBody(BaseModel):
    vi_provider: str | None = None
    vi_voice: str | None = None
    en_provider: str | None = None
    en_voice: str | None = None


class VoicePreviewBody(BaseModel):
    text: str
    lang: Literal["vi", "en"] = "vi"
    provider: str | None = None
    voice: str | None = None
    target_duration_s: float = Field(default=4.0, ge=0.5, le=60.0)


# ---------- Products ----------


@router.get("/products")
async def api_v1_list_products(
    request: Request,
    workspace_id: int | None = Query(default=None),
    include_hidden: bool = Query(default=False),
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    ws_id = resolve_workspace_id(paths.db_file, workspace_id)
    items = list_products(
        paths.db_file, include_hidden=include_hidden, workspace_id=ws_id
    )
    return JSONResponse({"products": items, "workspace_id": ws_id})


@router.post("/products", status_code=201)
async def api_v1_create_product(
    request: Request, body: ProductCreateBody
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    ws_id = resolve_workspace_id(paths.db_file, body.workspace_id, require_active=True)
    try:
        pid = create_product(
            paths.db_file,
            name=body.name,
            material=body.material,
            facts=body.facts,
            workspace_id=ws_id,
            actor="api",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse({"product": get_product(paths.db_file, pid)}, status_code=201)


@router.patch("/products/{product_id}")
async def api_v1_update_product(
    request: Request, product_id: int, body: ProductUpdateBody
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    existing = get_product(paths.db_file, product_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Product #{product_id} not found")
    try:
        update_product(
            paths.db_file,
            product_id,
            name=body.name if body.name is not None else str(existing["name"]),
            material=body.material if body.material is not None else str(existing["material"]),
            facts=body.facts if body.facts is not None else dict(existing["facts"]),
            actor="api",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse({"product": get_product(paths.db_file, product_id)})


@router.delete("/products/{product_id}")
async def api_v1_delete_product(request: Request, product_id: int) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    existing = get_product(paths.db_file, product_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Product #{product_id} not found")
    outcome = delete_or_hide_product(paths.db_file, product_id, actor="api")
    return JSONResponse({"outcome": outcome, "product_id": product_id})


# ---------- Footage ----------


def _serialize_footage_row(row: dict[str, Any], product_map: dict[int, str]) -> dict[str, Any]:
    pids = parse_int_list(row.get("product_ids_json"))
    rel = str(row.get("path") or "")
    return {
        "id": int(row["id"]),
        "workspace_id": int(row.get("workspace_id") or 1),
        "path": rel,
        "media_url": f"/files/{rel}" if rel and rel != "pending" else None,
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
            "footage": [_serialize_footage_row(r, pmap) for r in rows],
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
    ext = Path(file.filename or "upload.mp4").suffix.lower() or ".mp4"
    if ext not in ALLOWED_VIDEO_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Đuôi video không hợp lệ: {ext}")

    parsed_pids: list[int] = []
    for tok in product_ids.replace(";", ",").split(","):
        clean = tok.strip()
        if clean.isdigit():
            parsed_pids.append(int(clean))

    tmp_path = paths.work_dir / f"upload_{uuid.uuid4().hex}{ext}"
    tmp_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tmp_path.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                out.write(chunk)
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
            "footage": _serialize_footage_row(
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
            "footage": _serialize_footage_row(
                row, product_name_map(paths.db_file, workspace_id=ws_id)
            )
        },
        status_code=201,
    )


# ---------- Shots ----------


def _serialize_shot_row(row: dict[str, Any], pmap: dict[int, str]) -> dict[str, Any]:
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
        "media_url": f"/files/{src_rel}" if src_rel else None,
        "thumb_url": f"/files/{thumb_rel}" if thumb_rel else None,
    }


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
        item = _serialize_shot_row(r, pmap)
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

    next_desc = body.description.strip() if body.description is not None else str(row.get("description") or "")
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
    next_focus_x = round(float(body.focus_x), 4) if body.focus_x is not None else row.get("focus_x")

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
            "shot": _serialize_shot_row(
                updated, product_name_map(paths.db_file, workspace_id=ws_id)
            )
        }
    )


# ---------- Assets (Music, SFX, B-roll) ----------


def _serialize_asset(row: dict[str, Any]) -> dict[str, Any]:
    meta = loads_or(row.get("meta_json"), {})
    if not isinstance(meta, dict):
        meta = {}
    rel = str(row.get("path") or "")
    return {
        "id": int(row["id"]),
        "workspace_id": int(row.get("workspace_id") or 1),
        "kind": str(row.get("kind") or "music"),
        "path": rel,
        "media_url": f"/files/{rel}" if rel and rel != "pending" else None,
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
    return JSONResponse({"assets": [_serialize_asset(r) for r in rows], "workspace_id": ws_id})


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
    ext = Path(file.filename or "audio.wav").suffix.lower() or ".wav"
    if ext not in ALLOWED_AUDIO_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Đuôi audio không hợp lệ: {ext}")
    tmp_path = paths.work_dir / f"asset_up_{uuid.uuid4().hex}{ext}"
    tmp_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tmp_path.open("wb") as out:
            while chunk := await file.read(512 * 1024):
                out.write(chunk)
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
    return JSONResponse({"asset": _serialize_asset(row)}, status_code=201)


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
    return JSONResponse({"asset": _serialize_asset(row)}, status_code=201)


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


# ---------- Voices & TTS Preview ----------


@router.get("/voices")
async def api_v1_get_voices(request: Request) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    cfg = load_settings(paths.config_file)
    return JSONResponse(
        {
            "catalog": AVAILABLE_VOICE_CATALOG,
            "voice": cfg.voice.model_dump(mode="json"),
        }
    )


@router.put("/voices")
async def api_v1_update_voices(
    request: Request, body: VoicesUpdateBody
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    cfg = load_settings(paths.config_file)
    if body.vi_provider is not None:
        cfg.voice.vi_provider = body.vi_provider.strip() or "edge"
    if body.vi_voice is not None:
        cfg.voice.vi_voice = body.vi_voice.strip()
    if body.en_provider is not None:
        cfg.voice.en_provider = body.en_provider.strip() or "edge"
    if body.en_voice is not None:
        cfg.voice.en_voice = body.en_voice.strip()
    save_settings(paths.config_file, cfg)
    return JSONResponse({"voice": cfg.voice.model_dump(mode="json")})


@router.post("/voices/preview")
async def api_v1_preview_voice(
    request: Request, body: VoicePreviewBody
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    clean_text = body.text.strip()
    if not clean_text:
        raise HTTPException(status_code=400, detail="Text is required for TTS preview")
    cfg = load_settings(paths.config_file)
    prov = body.provider or (cfg.voice.en_provider if body.lang == "en" else cfg.voice.vi_provider)
    voice = body.voice or (cfg.voice.en_voice if body.lang == "en" else cfg.voice.vi_voice)

    tmp_work = paths.work_dir / f"preview_tts_{uuid.uuid4().hex}"
    previews_dir = paths.media_dir / "previews"
    previews_dir.mkdir(parents=True, exist_ok=True)
    try:
        track, warnings = await asyncio.to_thread(
            synthesize_speech_segments,
            [(clean_text, body.target_duration_s)],
            lang=body.lang,
            voice=voice,
            provider_name=prov,
            work_dir=tmp_work,
        )
        out_name = f"tts_{uuid.uuid4().hex[:12]}.wav"
        dest_wav = previews_dir / out_name
        shutil.copy2(track.audio_path, dest_wav)
    except TTSUnavailableError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        shutil.rmtree(tmp_work, ignore_errors=True)

    return JSONResponse(
        {
            "audio_url": f"/files/previews/{out_name}",
            "provider": track.provider,
            "duration_s": round(track.duration_s, 3),
            "applied_atempo": track.applied_atempo,
            "syllables": count_syllables(clean_text, body.lang),
            "word_timings": [asdict(w) for w in track.word_timings],
            "warnings": warnings,
        }
    )

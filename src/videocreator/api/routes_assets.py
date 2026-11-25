"""Audio asset management routes (music and SFX, Phase 05, FR-RND-03)."""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from videocreator import __version__
from videocreator.config import load_settings
from videocreator.db import get_conn, query_all, query_one, record_audit
from videocreator.jsonutil import loads_or
from videocreator.paths import AppPaths
from videocreator.services.assets import (
    ALLOWED_AUDIO_EXTENSIONS,
    MAX_AUDIO_UPLOAD_BYTES,
    import_audio_asset,
    probe_audio_duration,
)
from videocreator.templating import get_templates

router = APIRouter()

__all__ = [
    "ALLOWED_AUDIO_EXTENSIONS",
    "MAX_AUDIO_UPLOAD_BYTES",
    "import_audio_asset",
    "probe_audio_duration",
    "router",
]


@router.get("/assets", response_class=HTMLResponse)
async def assets_page(
    request: Request,
    msg: str | None = None,
) -> HTMLResponse:
    paths: AppPaths = request.app.state.paths
    cfg = load_settings(paths.config_file)
    templates = get_templates(paths)

    raw = query_all(
        paths.db_file,
        "SELECT * FROM assets WHERE kind IN ('music', 'sfx') ORDER BY id DESC",
    )
    assets: list[dict[str, Any]] = []
    for r in raw:
        meta = loads_or(r.get("meta_json"), {})
        assets.append({**r, "title": meta.get("title") or r["path"]})

    return templates.TemplateResponse(
        request,
        "assets.html",
        {
            "page": "assets",
            "settings": cfg,
            "assets": assets,
            "msg": msg,
            "version": __version__,
        },
    )


@router.post("/assets/upload")
async def upload_audio_asset(
    request: Request,
    file: UploadFile = File(...),
    kind: str = Form("music"),
    title: str = Form(""),
) -> RedirectResponse:
    paths: AppPaths = request.app.state.paths
    filename = file.filename or "audio.mp3"
    ext = Path(filename).suffix.lower() or ".mp3"
    if ext not in ALLOWED_AUDIO_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Đuôi nhạc '{ext}' không hợp lệ")

    clean_kind: Literal["music", "sfx"] = "sfx" if kind == "sfx" else "music"
    paths.work_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = paths.work_dir / f"upload_aud_{uuid.uuid4().hex}{ext}"
    try:
        total_bytes = 0
        with tmp_path.open("wb") as out_f:
            while chunk := await file.read(1024 * 1024):
                total_bytes += len(chunk)
                if total_bytes > MAX_AUDIO_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="File âm thanh vượt quá giới hạn 50 MB")
                out_f.write(chunk)
        import_audio_asset(paths, tmp_path, kind=clean_kind, title=title or Path(filename).stem)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        tmp_path.unlink(missing_ok=True)

    return RedirectResponse(url="/assets?msg=uploaded", status_code=303)


@router.post("/assets/{asset_id}/delete")
async def delete_audio_asset(request: Request, asset_id: int) -> RedirectResponse:
    paths: AppPaths = request.app.state.paths
    row = query_one(paths.db_file, "SELECT * FROM assets WHERE id = ?", (asset_id,))
    if row is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    rel_path = str(row.get("path") or "")
    if rel_path:
        (paths.media_dir / rel_path).unlink(missing_ok=True)
    with get_conn(paths.db_file) as conn:
        conn.execute("DELETE FROM assets WHERE id = ?", (asset_id,))
        record_audit(
            conn,
            actor="ui",
            action="asset.deleted",
            object_type="asset",
            object_id=asset_id,
            detail=rel_path,
        )
    return RedirectResponse(url="/assets?msg=deleted", status_code=303)

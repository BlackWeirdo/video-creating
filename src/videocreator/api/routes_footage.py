"""Footage import, analysis job handler, shot library, and safe media serving routes (Phase 03)."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from videocreator import __version__
from videocreator.api.view_models import enrich_footage_rows
from videocreator.config import load_settings
from videocreator.db import get_conn, query_all, query_one, record_audit
from videocreator.jobs import enqueue_job
from videocreator.paths import AppPaths
from videocreator.pipeline.footage_import import (
    ALLOWED_VIDEO_EXTENSIONS,
    MAX_UPLOAD_BYTES,
    DuplicateFootageError,
    import_footage_file,
)
from videocreator.pipeline.probe import ProbeError
from videocreator.products import list_products, product_name_map
from videocreator.templating import get_templates

logger = logging.getLogger("videocreator.footage")

router = APIRouter()


@router.get("/footage", response_class=HTMLResponse)
async def footage_page(
    request: Request,
    msg: str | None = None,
    err: str | None = None,
) -> HTMLResponse:
    paths: AppPaths = request.app.state.paths
    cfg = load_settings(paths.config_file)
    templates = get_templates(paths)
    products = list_products(paths.db_file, include_hidden=False)
    product_map = product_name_map(paths.db_file)

    raw_rows = query_all(paths.db_file, "SELECT * FROM footage ORDER BY id DESC")
    footage_items = enrich_footage_rows(paths.db_file, raw_rows, product_map)

    return templates.TemplateResponse(
        request,
        "footage.html",
        {
            "page": "footage",
            "settings": cfg,
            "products": products,
            "footage_items": footage_items,
            "msg": msg,
            "err": err,
            "version": __version__,
        },
    )


@router.post("/footage/upload")
async def upload_footage(
    request: Request,
    file: UploadFile = File(...),
    product_ids: list[int] = Form(default=[]),
    no_product: bool = Form(default=False),
) -> RedirectResponse:
    paths: AppPaths = request.app.state.paths
    filename = file.filename or "upload.mp4"
    ext = Path(filename).suffix.lower() or ".mp4"
    if ext not in ALLOWED_VIDEO_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Đuôi file '{ext}' không được phép. Chỉ nhận: {', '.join(sorted(ALLOWED_VIDEO_EXTENSIONS))}",
        )

    paths.work_dir.mkdir(parents=True, exist_ok=True)
    tmp_upload = paths.work_dir / f"upload_{uuid.uuid4().hex}{ext}"
    try:
        total_bytes = 0
        with tmp_upload.open("wb") as out_f:
            while chunk := await file.read(1024 * 1024):
                total_bytes += len(chunk)
                if total_bytes > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="File video vượt quá giới hạn 2 GB")
                out_f.write(chunk)
        await asyncio.to_thread(
            import_footage_file,
            paths,
            tmp_upload,
            product_ids=product_ids,
            no_product=no_product,
            actor="ui",
        )
    except DuplicateFootageError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (ValueError, ProbeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        tmp_upload.unlink(missing_ok=True)

    return RedirectResponse(url="/footage?msg=imported", status_code=303)


@router.post("/footage/import-path")
async def import_footage_by_path(
    request: Request,
    local_path: str = Form(...),
    product_ids: list[int] = Form(default=[]),
    no_product: bool = Form(default=False),
) -> RedirectResponse:
    paths: AppPaths = request.app.state.paths
    target = Path(local_path.strip().strip('"')).expanduser()
    if not target.exists():
        raise HTTPException(status_code=400, detail=f"Đường dẫn không tồn tại: {target}")

    files_to_import: list[Path] = []
    if target.is_file():
        files_to_import.append(target)
    elif target.is_dir():
        for p in sorted(target.iterdir()):
            if p.is_file() and p.suffix.lower() in ALLOWED_VIDEO_EXTENSIONS:
                files_to_import.append(p)
        if not files_to_import:
            raise HTTPException(
                status_code=400, detail="Không tìm thấy file video hợp lệ trong thư mục"
            )

    imported_count = 0
    for fpath in files_to_import:
        try:
            await asyncio.to_thread(
                import_footage_file,
                paths,
                fpath,
                product_ids=product_ids,
                no_product=no_product,
                actor="ui",
            )
            imported_count += 1
        except DuplicateFootageError as exc:
            if len(files_to_import) == 1:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (ValueError, ProbeError) as exc:
            if len(files_to_import) == 1:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

    return RedirectResponse(url=f"/footage?msg=imported_{imported_count}", status_code=303)


@router.post("/footage/{footage_id}/crop")
async def update_footage_crop(
    request: Request,
    footage_id: int,
    mode: str = Form("blur_pad"),
    x_offset_ratio: float = Form(0.5),
) -> RedirectResponse:
    paths: AppPaths = request.app.state.paths
    clean_mode = "crop" if mode == "crop" else "blur_pad"
    clamped_x = max(0.0, min(1.0, float(x_offset_ratio)))
    crop_payload = json.dumps({"mode": clean_mode, "x_offset_ratio": round(clamped_x, 3)})

    with get_conn(paths.db_file) as conn:
        cur = conn.execute(
            "UPDATE footage SET crop_json = ? WHERE id = ?",
            (crop_payload, footage_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Footage not found")
        record_audit(
            conn,
            actor="ui",
            action="footage.update_crop",
            object_type="footage",
            object_id=footage_id,
            detail=crop_payload,
        )
    return RedirectResponse(url="/footage?msg=crop_saved", status_code=303)


@router.post("/footage/{footage_id}/reanalyse")
async def reanalyse_footage(request: Request, footage_id: int) -> RedirectResponse:
    paths: AppPaths = request.app.state.paths
    row = query_one(paths.db_file, "SELECT id FROM footage WHERE id = ?", (footage_id,))
    if row is None:
        raise HTTPException(status_code=404, detail="Footage not found")
    enqueue_job(paths.db_file, "analyse", ref_id=footage_id)
    return RedirectResponse(url="/footage?msg=requeued", status_code=303)

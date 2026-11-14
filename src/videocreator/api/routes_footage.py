"""Footage import, analysis job handler, shot library, and safe media serving routes (Phase 03)."""
from __future__ import annotations

import hashlib
import json
import logging
import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from videocreator import __version__
from videocreator.api.routes_products import list_products
from videocreator.config import load_settings
from videocreator.db import get_conn, query_all, query_one, record_audit
from videocreator.jobs import enqueue_job
from videocreator.paths import AppPaths
from videocreator.pipeline.probe import ProbeError, probe_video
from videocreator.pipeline.shots import detect_shots
from videocreator.pipeline.thumbs import extract_thumbnail
from videocreator.state import transition_footage

logger = logging.getLogger("videocreator.footage")

router = APIRouter()

ALLOWED_VIDEO_EXTENSIONS: set[str] = {".mp4", ".mov", ".mkv", ".webm"}
MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB


class DuplicateFootageError(ValueError):
    """Raised when a footage file with the same SHA-256 already exists."""


def compute_sha256(file_path: Path) -> str:
    h = hashlib.sha256()
    with file_path.open("rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def import_footage_file(
    paths: AppPaths,
    source_file: Path,
    *,
    product_ids: list[int],
    no_product: bool = False,
    enqueue_analysis: bool = True,
    actor: str = "ui",
) -> int:
    """Validates, probes, deduplicates by sha256, copies into media/footage/<id>.mp4,
    and optionally enqueues the `analyse` job."""
    if not source_file.exists() or not source_file.is_file():
        raise ValueError(f"Source file does not exist: {source_file}")

    ext = source_file.suffix.lower()
    if ext not in ALLOWED_VIDEO_EXTENSIONS:
        raise ValueError(
            f"Unsupported video extension '{ext}'. Allowed: {', '.join(sorted(ALLOWED_VIDEO_EXTENSIONS))}"
        )

    clean_pids = sorted({int(pid) for pid in product_ids if int(pid) > 0})
    if not clean_pids and not no_product:
        raise ValueError(
            "Must select at least one product or explicitly mark 'no_product' (FR-FTG-03)"
        )
    if no_product:
        clean_pids = []

    file_size = source_file.stat().st_size
    if file_size <= 0 or file_size > MAX_UPLOAD_BYTES:
        raise ValueError(f"Invalid video file size ({file_size} bytes)")

    sha256 = compute_sha256(source_file)
    existing = query_one(
        paths.db_file, "SELECT id FROM footage WHERE sha256 = ?", (sha256,)
    )
    if existing is not None:
        raise DuplicateFootageError(
            f"Duplicate footage rejected (matches footage #{existing['id']}, sha256={sha256[:12]}...)"
        )

    info = probe_video(source_file)
    crop_data: dict[str, Any] | None = None
    if info.is_landscape:
        crop_data = {"mode": "blur_pad", "x_offset_ratio": 0.5}

    with get_conn(paths.db_file) as conn:
        cur = conn.execute(
            """
            INSERT INTO footage (
                path, sha256, duration_s, width, height, orientation,
                crop_json, product_ids_json, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'imported')
            """,
            (
                "pending",
                sha256,
                info.duration_s,
                info.width,
                info.height,
                info.orientation,
                json.dumps(crop_data) if crop_data else None,
                json.dumps(clean_pids),
            ),
        )
        footage_id = int(cur.lastrowid or 0)
        rel_path = f"footage/{footage_id}.mp4"
        dest_file = paths.media_dir / rel_path
        dest_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, dest_file)

        conn.execute(
            "UPDATE footage SET path = ? WHERE id = ?",
            (rel_path, footage_id),
        )
        record_audit(
            conn,
            actor=actor,
            action="footage.imported",
            object_type="footage",
            object_id=footage_id,
            detail=f"sha256={sha256[:12]}, {info.width}x{info.height}, {info.duration_s}s",
        )

    if enqueue_analysis:
        enqueue_job(paths.db_file, "analyse", ref_id=footage_id)

    return footage_id


def run_analyse_footage(paths: AppPaths, footage_id: int) -> str:
    """Job handler for `analyse`: detects shots via rea-video, extracts thumbnails,
    and saves shots in a single transaction."""
    row = query_one(paths.db_file, "SELECT * FROM footage WHERE id = ?", (footage_id,))
    if row is None:
        raise LookupError(f"Footage #{footage_id} does not exist")

    video_path = paths.media_dir / str(row["path"])
    duration_s = float(row["duration_s"] or 0.0)
    product_ids_json = str(row.get("product_ids_json") or "[]")
    try:
        product_ids = json.loads(product_ids_json)
    except json.JSONDecodeError:
        product_ids = []
    has_product = 1 if product_ids else 0

    transition_footage(paths.db_file, footage_id, "analysing", error=None)
    work_dir = paths.work_dir / f"analyse_{footage_id}"
    if work_dir.exists():
        shutil.rmtree(work_dir, ignore_errors=True)

    try:
        if duration_s <= 0:
            info = probe_video(video_path)
            duration_s = info.duration_s

        spans, rea_log = detect_shots(
            video_path,
            total_duration_s=duration_s,
            work_dir=work_dir,
        )
        shot_records: list[tuple[int, float, float, str]] = []
        for idx, span in enumerate(spans, start=1):
            rel_thumb = f"thumbs/shot_{footage_id}_{idx:03d}.jpg"
            abs_thumb = paths.media_dir / rel_thumb
            extract_thumbnail(video_path, span.midpoint_s, abs_thumb)
            shot_records.append((idx, span.start_s, span.end_s, rel_thumb))

        with get_conn(paths.db_file) as conn:
            conn.execute("DELETE FROM shots WHERE footage_id = ?", (footage_id,))
            for idx, start_s, end_s, rel_thumb in shot_records:
                conn.execute(
                    """
                    INSERT INTO shots (
                        footage_id, idx, start_s, end_s, description,
                        tags_json, has_product, product_ids_json, quality, thumb_path
                    )
                    VALUES (?, ?, ?, ?, '', '[]', ?, ?, 3, ?)
                    """,
                    (
                        footage_id,
                        idx,
                        start_s,
                        end_s,
                        has_product,
                        product_ids_json,
                        rel_thumb,
                    ),
                )
            conn.execute(
                "UPDATE footage SET status = 'analysed', error = NULL WHERE id = ?",
                (footage_id,),
            )
            record_audit(
                conn,
                actor="worker",
                action="footage.analysed",
                object_type="footage",
                object_id=footage_id,
                detail=f"{len(shot_records)} shots",
            )
        shutil.rmtree(work_dir, ignore_errors=True)
        return f"Detected {len(shot_records)} shots\n{rea_log}"
    except Exception as exc:
        err_msg = str(exc)[:500]
        with get_conn(paths.db_file) as conn:
            conn.execute(
                "UPDATE footage SET status = 'failed', error = ? WHERE id = ?",
                (err_msg, footage_id),
            )
        raise


def _enrich_footage_rows(
    db_file: Path, rows: list[dict[str, Any]], product_map: dict[int, str]
) -> list[dict[str, Any]]:
    shot_counts: dict[int, int] = {}
    for r in query_all(
        db_file,
        "SELECT footage_id, COUNT(*) AS cnt FROM shots WHERE footage_id IS NOT NULL GROUP BY footage_id",
    ):
        shot_counts[int(r["footage_id"])] = int(r["cnt"])

    job_logs: dict[int, str] = {}
    for j in query_all(
        db_file,
        "SELECT ref_id, log_tail, error FROM jobs WHERE kind = 'analyse' AND ref_id IS NOT NULL ORDER BY id DESC",
    ):
        fid = int(j["ref_id"])
        if fid not in job_logs and (j.get("log_tail") or j.get("error")):
            job_logs[fid] = str(j.get("error") or j.get("log_tail") or "")[-600:]

    result: list[dict[str, Any]] = []
    for r in rows:
        fid = int(r["id"])
        try:
            pids = [int(x) for x in json.loads(r.get("product_ids_json") or "[]")]
        except Exception:
            pids = []
        try:
            crop = json.loads(r["crop_json"]) if r.get("crop_json") else None
        except Exception:
            crop = None
        w = int(r.get("width") or 0)
        h = int(r.get("height") or 0)
        result.append(
            {
                **r,
                "product_ids": pids,
                "product_names": [product_map.get(pid, f"#{pid}") for pid in pids],
                "shot_count": shot_counts.get(fid, 0),
                "is_landscape": str(r.get("orientation")) == "landscape",
                "is_low_res": min(w, h) < 1080 if (w > 0 and h > 0) else False,
                "crop": crop or {"mode": "blur_pad", "x_offset_ratio": 0.5},
                "job_log_tail": job_logs.get(fid, ""),
            }
        )
    return result


@router.get("/footage", response_class=HTMLResponse)
async def footage_page(
    request: Request,
    msg: str | None = None,
    err: str | None = None,
) -> HTMLResponse:
    paths: AppPaths = request.app.state.paths
    cfg = load_settings(paths.config_file)
    templates = Jinja2Templates(directory=str(paths.templates_dir))
    products = list_products(paths.db_file, include_hidden=False)
    all_products = list_products(paths.db_file, include_hidden=True)
    product_map = {p["id"]: p["name"] for p in all_products}

    raw_rows = query_all(paths.db_file, "SELECT * FROM footage ORDER BY id DESC")
    footage_items = _enrich_footage_rows(paths.db_file, raw_rows, product_map)

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

    tmp_upload = paths.work_dir / f"upload_{hashlib.md5(filename.encode('utf-8')).hexdigest()}{ext}"
    try:
        with tmp_upload.open("wb") as out_f:
            while chunk := await file.read(1024 * 1024):
                out_f.write(chunk)
        import_footage_file(
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
            import_footage_file(
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


@router.get("/shots", response_class=HTMLResponse)
async def shots_page(
    request: Request,
    footage_id: int | None = None,
    product_id: int | None = None,
    tag: str | None = None,
    msg: str | None = None,
) -> HTMLResponse:
    paths: AppPaths = request.app.state.paths
    cfg = load_settings(paths.config_file)
    templates = Jinja2Templates(directory=str(paths.templates_dir))

    all_products = list_products(paths.db_file, include_hidden=True)
    active_products = [p for p in all_products if not p["hidden"]]
    product_map = {p["id"]: p["name"] for p in all_products}
    footage_list = query_all(paths.db_file, "SELECT id, path, status FROM footage ORDER BY id DESC")

    sql = """
        SELECT s.*, f.path AS footage_path
        FROM shots s
        LEFT JOIN footage f ON s.footage_id = f.id
        WHERE 1=1
    """
    params: list[Any] = []
    if footage_id is not None:
        sql += " AND s.footage_id = ?"
        params.append(footage_id)
    sql += " ORDER BY s.footage_id DESC, s.idx ASC"

    raw_shots = query_all(paths.db_file, sql, params)
    shots: list[dict[str, Any]] = []
    all_tags: set[str] = set()
    for r in raw_shots:
        try:
            pids = [int(x) for x in json.loads(r.get("product_ids_json") or "[]")]
        except Exception:
            pids = []
        try:
            tags = [str(t) for t in json.loads(r.get("tags_json") or "[]")]
        except Exception:
            tags = []
        for t in tags:
            all_tags.add(t)

        if product_id is not None and product_id not in pids:
            continue
        if tag and tag.strip() and tag.strip() not in tags:
            continue

        shots.append(
            {
                **r,
                "duration_s": round(float(r["end_s"]) - float(r["start_s"]), 2),
                "product_ids": pids,
                "product_names": [product_map.get(pid, f"#{pid}") for pid in pids],
                "tags": tags,
                "tags_str": ", ".join(tags),
            }
        )

    return templates.TemplateResponse(
        request,
        "shots.html",
        {
            "page": "shots",
            "settings": cfg,
            "shots": shots,
            "products": active_products,
            "footage_list": footage_list,
            "all_tags": sorted(all_tags),
            "filter_footage_id": footage_id,
            "filter_product_id": product_id,
            "filter_tag": tag or "",
            "msg": msg,
            "version": __version__,
        },
    )


@router.post("/shots/{shot_id}/update")
async def update_shot(
    request: Request,
    shot_id: int,
    product_ids: list[int] = Form(default=[]),
    no_product: bool = Form(default=False),
    tags: str = Form(""),
    description: str = Form(""),
) -> RedirectResponse:
    paths: AppPaths = request.app.state.paths
    clean_pids = [] if no_product else sorted({int(x) for x in product_ids if int(x) > 0})
    has_product = 0 if (no_product or not clean_pids) else 1
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]

    with get_conn(paths.db_file) as conn:
        cur = conn.execute(
            """
            UPDATE shots
            SET has_product = ?,
                product_ids_json = ?,
                tags_json = ?,
                description = ?
            WHERE id = ?
            """,
            (
                has_product,
                json.dumps(clean_pids),
                json.dumps(tag_list, ensure_ascii=False),
                description.strip(),
                shot_id,
            ),
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Shot not found")
        record_audit(
            conn,
            actor="ui",
            action="shot.updated",
            object_type="shot",
            object_id=shot_id,
            detail=f"has_product={has_product}, products={clean_pids}",
        )
    return RedirectResponse(url="/shots?msg=updated", status_code=303)


@router.get("/media/{subpath:path}")
async def serve_media(request: Request, subpath: str) -> FileResponse:
    """Safely serves media files inside `paths.media_dir` with Range support, blocking traversal (NFR-SEC-05)."""
    paths: AppPaths = request.app.state.paths
    media_root = paths.media_dir.resolve()
    if ".." in Path(subpath).parts:
        raise HTTPException(status_code=403, detail="Path traversal forbidden")
    target = (media_root / subpath).resolve()
    if not target.is_relative_to(media_root) or not target.is_file():
        raise HTTPException(status_code=404, detail="Media file not found")
    return FileResponse(target)

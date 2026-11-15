"""Routes for trend watchlist, ranked trend results, reference upload, and remix suggestions (Phases 12 & 13)."""
from __future__ import annotations
import asyncio
import json
import logging
import shutil
from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from videocreator import __version__
from videocreator.config import load_settings
from videocreator.db import get_conn, query_all, query_one
from videocreator.jobs import enqueue_job
from videocreator.jsonutil import loads_or
from videocreator.paths import AppPaths
from videocreator.templating import get_templates
from videocreator.timeutil import UTC_ISO_FORMAT
from videocreator.trends.link_parse import PLATFORM_LABELS
from videocreator.trends.links import add_pasted_link
from videocreator.trends.scan import build_trend_sources

router = APIRouter()
logger = logging.getLogger("videocreator.api.routes_trends")


@router.get("/trends", response_class=HTMLResponse)
async def trends_page(
    request: Request,
    source: str | None = None,
    msg: str | None = None,
    err: str | None = None,
) -> HTMLResponse:
    paths: AppPaths = request.app.state.paths
    cfg = load_settings(paths.config_file)
    templates = get_templates(paths)

    sources = build_trend_sources(paths, request.app.state.secrets)
    source_statuses = {name: src.status() for name, src in sources.items()}
    # Pasted links are stored under the platform name ('facebook', 'instagram'), whose scanning
    # is manual or absent; their filter buttons show no "disabled" note because pasted items exist.
    for platform in PLATFORM_LABELS:
        source_statuses[platform] = (True, None)

    if source and source in source_statuses:
        rows = query_all(
            paths.db_file,
            "SELECT * FROM trend_items WHERE source = ? ORDER BY score DESC, id DESC LIMIT 100",
            (source,),
        )
    else:
        rows = query_all(
            paths.db_file,
            "SELECT * FROM trend_items ORDER BY source ASC, score DESC, id DESC LIMIT 150",
        )

    items = []
    for r in rows:
        metrics = loads_or(r.get("metrics_json"), {})
        try:
            analysis = json.loads(str(r["analysis_json"])) if r.get("analysis_json") else None
        except Exception:
            analysis = None
        items.append({**r, "metrics": metrics, "analysis": analysis})

    return templates.TemplateResponse(
        request,
        "trends.html",
        {
            "page": "trends",
            "settings": cfg,
            "source_filter": source or "",
            "source_statuses": source_statuses,
            "trend_items": items,
            "msg": msg,
            "err": err,
            "version": __version__,
        },
    )


@router.post("/trends/scan")
async def trigger_scan_route(request: Request) -> RedirectResponse:
    paths: AppPaths = request.app.state.paths
    enqueue_job(paths.db_file, "scan_trends", ref_id=0)
    return RedirectResponse(url="/trends?msg=scan_queued", status_code=303)


@router.post("/trends/add-link")
async def add_link_route(request: Request, url: str = Form(...)) -> RedirectResponse:
    """Adds one pasted Facebook/Instagram video (read off the event loop: yt-dlp may take seconds)."""
    paths: AppPaths = request.app.state.paths
    try:
        _trend_id, item = await asyncio.to_thread(add_pasted_link, paths, url, actor="ui")
    except ValueError as exc:
        return RedirectResponse(url=f"/trends?err={quote(str(exc))}", status_code=303)
    except Exception:
        logger.exception("add-link failed for %s", url)
        return RedirectResponse(
            url=f"/trends?err={quote('Lỗi nội bộ khi đọc link. Đã ghi vào log; hãy thử lại sau.')}",
            status_code=303,
        )
    return RedirectResponse(url=f"/trends?source={item.source}&msg=link_added", status_code=303)


@router.post("/trends/{item_id}/upload-reference")
async def upload_reference_video_route(
    request: Request,
    item_id: int,
    file: UploadFile = File(...),
) -> RedirectResponse:
    """Manual fallback for Ad Library reference video upload (`FR-TRD-05`: stored in `media/reference/`)."""
    paths: AppPaths = request.app.state.paths
    row = query_one(paths.db_file, "SELECT id FROM trend_items WHERE id = ?", (item_id,))
    if row is None:
        raise HTTPException(status_code=404, detail="Trend item not found")

    paths.reference_dir.mkdir(parents=True, exist_ok=True)
    rel_path = f"reference/ref_{item_id}.mp4"
    dest_file = paths.media_dir / rel_path
    with dest_file.open("wb") as out_f:
        await asyncio.to_thread(shutil.copyfileobj, file.file, out_f)

    dl_iso = datetime.now(timezone.utc).strftime(UTC_ISO_FORMAT)
    with get_conn(paths.db_file) as conn:
        conn.execute(
            """
            INSERT INTO reference_videos (trend_item_id, path, downloaded_at, deleted_at)
            VALUES (?, ?, ?, NULL)
            ON CONFLICT(trend_item_id) DO UPDATE SET
                path = excluded.path,
                downloaded_at = excluded.downloaded_at,
                deleted_at = NULL
            """,
            (item_id, rel_path, dl_iso),
        )
    return RedirectResponse(url="/trends?msg=reference_uploaded", status_code=303)

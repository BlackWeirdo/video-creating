"""Routes for trend watchlist, ranked trend results, reference upload, and remix suggestions (Phases 12 & 13)."""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from videocreator import __version__
from videocreator.config import load_settings
from videocreator.db import get_conn, query_all, query_one
from videocreator.jobs import enqueue_job
from videocreator.paths import AppPaths
from videocreator.trends.analyse import analyse_top_trends
from videocreator.trends.scan import build_trend_sources, scan_all
from videocreator.trends.suggest import (
    accept_suggestion,
    dismiss_suggestion,
    make_suggestions,
)

router = APIRouter()


def run_scan_and_suggest_job(paths: AppPaths, _ref_id: int = 0) -> str:
    """Runs trend scan -> top-K structure analysis -> suggestion generation."""
    scan_res = scan_all(paths)
    analysed = analyse_top_trends(paths)
    created_sugs = make_suggestions(paths)
    return (
        f"Scan upserted={scan_res['upserted']}, analysed={len(analysed)}, "
        f"suggestions={len(created_sugs)}"
    )


@router.get("/watchlist", response_class=HTMLResponse)
async def watchlist_page(
    request: Request,
    msg: str | None = None,
) -> HTMLResponse:
    paths: AppPaths = request.app.state.paths
    cfg = load_settings(paths.config_file)
    templates = Jinja2Templates(directory=str(paths.templates_dir))

    sources = build_trend_sources(paths, request.app.state.secrets)
    source_statuses: list[dict[str, Any]] = []
    for name, src in sources.items():
        ok, reason = src.status()
        source_statuses.append(
            {
                "name": name,
                "kinds": ", ".join(src.kinds),
                "enabled": ok,
                "reason": reason or "Đang bật",
            }
        )

    watch_items = query_all(
        paths.db_file, "SELECT * FROM watch_items ORDER BY source, id ASC"
    )
    return templates.TemplateResponse(
        request,
        "watchlist.html",
        {
            "page": "trends",
            "settings": cfg,
            "source_statuses": source_statuses,
            "watch_items": watch_items,
            "msg": msg,
            "version": __version__,
        },
    )


@router.post("/watchlist/add")
async def add_watch_item_route(
    request: Request,
    source: str = Form("youtube"),
    kind: str = Form("keyword"),
    value: str = Form(...),
) -> RedirectResponse:
    paths: AppPaths = request.app.state.paths
    clean_val = value.strip()
    if not clean_val:
        raise HTTPException(status_code=400, detail="Giá trị theo dõi không được rỗng")

    with get_conn(paths.db_file) as conn:
        conn.execute(
            """
            INSERT INTO watch_items (source, kind, value, enabled)
            VALUES (?, ?, ?, 1)
            ON CONFLICT(source, kind, value) DO UPDATE SET enabled = 1
            """,
            (source.strip(), kind.strip(), clean_val),
        )
    return RedirectResponse(url="/watchlist?msg=added", status_code=303)


@router.post("/watchlist/{item_id}/toggle")
async def toggle_watch_item_route(request: Request, item_id: int) -> RedirectResponse:
    paths: AppPaths = request.app.state.paths
    with get_conn(paths.db_file) as conn:
        conn.execute(
            "UPDATE watch_items SET enabled = CASE WHEN enabled = 1 THEN 0 ELSE 1 END WHERE id = ?",
            (item_id,),
        )
    return RedirectResponse(url="/watchlist?msg=toggled", status_code=303)


@router.post("/watchlist/{item_id}/delete")
async def delete_watch_item_route(request: Request, item_id: int) -> RedirectResponse:
    paths: AppPaths = request.app.state.paths
    with get_conn(paths.db_file) as conn:
        conn.execute("DELETE FROM watch_items WHERE id = ?", (item_id,))
    return RedirectResponse(url="/watchlist?msg=deleted", status_code=303)


@router.get("/trends", response_class=HTMLResponse)
async def trends_page(
    request: Request,
    source: str | None = None,
    msg: str | None = None,
) -> HTMLResponse:
    paths: AppPaths = request.app.state.paths
    cfg = load_settings(paths.config_file)
    templates = Jinja2Templates(directory=str(paths.templates_dir))

    sources = build_trend_sources(paths, request.app.state.secrets)
    source_statuses = {name: src.status() for name, src in sources.items()}

    if source and source in sources:
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
        try:
            metrics = json.loads(str(r.get("metrics_json") or "{}"))
        except Exception:
            metrics = {}
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
            "version": __version__,
        },
    )


@router.post("/trends/scan")
async def trigger_scan_route(request: Request) -> RedirectResponse:
    paths: AppPaths = request.app.state.paths
    enqueue_job(paths.db_file, "scan_trends", ref_id=0)
    return RedirectResponse(url="/trends?msg=scan_queued", status_code=303)


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
        shutil.copyfileobj(file.file, out_f)

    dl_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
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


@router.get("/suggestions", response_class=HTMLResponse)
async def suggestions_page(
    request: Request,
    msg: str | None = None,
) -> HTMLResponse:
    paths: AppPaths = request.app.state.paths
    cfg = load_settings(paths.config_file)
    templates = Jinja2Templates(directory=str(paths.templates_dir))

    rows = query_all(
        paths.db_file,
        """
        SELECT s.*, t.source, t.author, t.url AS ref_url, t.score
        FROM suggestions s
        LEFT JOIN trend_items t ON s.trend_item_id = t.id
        ORDER BY s.id DESC
        """,
    )
    suggestions = []
    for r in rows:
        try:
            formula = json.loads(str(r.get("formula_json") or "{}"))
        except Exception:
            formula = {}
        suggestions.append({**r, "formula": formula})

    return templates.TemplateResponse(
        request,
        "suggestions.html",
        {
            "page": "suggestions",
            "settings": cfg,
            "suggestions": suggestions,
            "msg": msg,
            "version": __version__,
        },
    )


@router.post("/suggestions/{suggestion_id}/accept")
async def accept_suggestion_route(
    request: Request,
    suggestion_id: int,
    count: int = Form(1),
) -> RedirectResponse:
    paths: AppPaths = request.app.state.paths
    job_id = accept_suggestion(paths, suggestion_id, count=count, actor="ui")
    msg_key = "accepted" if job_id is not None else "already_handled"
    return RedirectResponse(url=f"/suggestions?msg={msg_key}", status_code=303)


@router.post("/suggestions/{suggestion_id}/dismiss")
async def dismiss_suggestion_route(
    request: Request,
    suggestion_id: int,
) -> RedirectResponse:
    paths: AppPaths = request.app.state.paths
    won = dismiss_suggestion(paths.db_file, suggestion_id, actor="ui")
    msg_key = "dismissed" if won else "already_handled"
    return RedirectResponse(url=f"/suggestions?msg={msg_key}", status_code=303)

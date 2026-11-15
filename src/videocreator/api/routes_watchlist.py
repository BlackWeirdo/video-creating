"""Watchlist routes: sources, keywords, hashtags and accounts to scan for trends."""
from __future__ import annotations

from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from videocreator import __version__
from videocreator.config import load_settings
from videocreator.db import get_conn, query_all
from videocreator.paths import AppPaths
from videocreator.templating import get_templates
from videocreator.trends.apify import APIFY_SOURCE_CLASSES
from videocreator.trends.apify_watch import normalize_apify_watch
from videocreator.trends.facebook import normalize_facebook_source
from videocreator.trends.scan import build_trend_sources

router = APIRouter()


@router.get("/watchlist", response_class=HTMLResponse)
async def watchlist_page(
    request: Request,
    msg: str | None = None,
    err: str | None = None,
) -> HTMLResponse:
    paths: AppPaths = request.app.state.paths
    cfg = load_settings(paths.config_file)
    templates = get_templates(paths)

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
            "err": err,
            "version": __version__,
        },
    )


def _watchlist_error(message: str) -> RedirectResponse:
    return RedirectResponse(url=f"/watchlist?err={quote(message)}", status_code=303)


@router.post("/watchlist/add")
async def add_watch_item_route(
    request: Request,
    source: str = Form("youtube"),
    kind: str = Form("keyword"),
    value: str = Form(...),
) -> RedirectResponse:
    paths: AppPaths = request.app.state.paths
    src_name, kind_name, clean_val = source.strip(), kind.strip(), value.strip()
    if not clean_val:
        return _watchlist_error("Giá trị theo dõi không được rỗng.")
    adapter = build_trend_sources(paths, request.app.state.secrets).get(src_name)
    if adapter is None:
        return _watchlist_error(f"Nguồn '{src_name}' không tồn tại.")
    if kind_name not in adapter.kinds:
        return _watchlist_error(
            f"Nguồn {src_name} chỉ nhận loại: {', '.join(adapter.kinds)}."
        )
    try:
        if isinstance(adapter, APIFY_SOURCE_CLASSES):
            clean_val = normalize_apify_watch(src_name, kind_name, clean_val)
        elif src_name == "facebook":
            clean_val = normalize_facebook_source(clean_val)
    except ValueError as exc:
        return _watchlist_error(str(exc))
    source, kind = src_name, kind_name

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

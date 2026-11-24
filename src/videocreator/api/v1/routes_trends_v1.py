"""Workspace-scoped Watchlist, Trends, rea-video analysis & Suggestions endpoints for `/api/v1`."""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from videocreator.api.v1.deps import resolve_workspace_id
from videocreator.db import get_conn, query_all, query_one, record_audit
from videocreator.jobs import enqueue_job
from videocreator.jsonutil import loads_or
from videocreator.paths import AppPaths
from videocreator.secrets_store import SecretsStore
from videocreator.trends.analyse_queue import enqueue_trend_analysis
from videocreator.trends.apify import APIFY_SOURCE_CLASSES
from videocreator.trends.apify_watch import normalize_apify_watch
from videocreator.trends.facebook import normalize_facebook_source
from videocreator.trends.links import add_pasted_link
from videocreator.trends.scan import build_trend_sources
from videocreator.trends.suggestion_actions import accept_suggestion, dismiss_suggestion

router = APIRouter()


class WatchItemCreateBody(BaseModel):
    workspace_id: int | None = None
    source: str = "youtube"
    kind: str = "keyword"
    value: str


class WatchItemPatchBody(BaseModel):
    enabled: bool


class TrendScanBody(BaseModel):
    workspace_id: int | None = None


class TrendLinkBody(BaseModel):
    workspace_id: int | None = None
    url: str


class SuggestionAcceptBody(BaseModel):
    workspace_id: int | None = None
    count: int = 1
    auto_render: bool = False
    render_mode: str | None = None


# ---------- Watchlist ----------


@router.get("/watchlist")
async def api_v1_list_watchlist(
    request: Request,
    workspace_id: int | None = Query(default=None),
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    secrets: SecretsStore = request.app.state.secrets
    ws_id = resolve_workspace_id(paths.db_file, workspace_id)

    sources = build_trend_sources(paths, secrets)
    source_statuses = []
    for name, src in sources.items():
        ok, reason = src.status()
        source_statuses.append(
            {
                "name": name,
                "kinds": list(src.kinds),
                "enabled": ok,
                "reason": reason or "Đang bật",
            }
        )
    items = query_all(
        paths.db_file,
        "SELECT * FROM watch_items WHERE workspace_id = ? ORDER BY source, id ASC",
        (ws_id,),
    )
    return JSONResponse(
        {"watchlist": items, "sources": source_statuses, "workspace_id": ws_id}
    )


@router.post("/watchlist", status_code=201)
async def api_v1_create_watch_item(
    request: Request, body: WatchItemCreateBody
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    secrets: SecretsStore = request.app.state.secrets
    ws_id = resolve_workspace_id(paths.db_file, body.workspace_id, require_active=True)
    src_name = body.source.strip()
    kind_name = body.kind.strip()
    clean_val = body.value.strip()
    if not clean_val:
        raise HTTPException(status_code=400, detail="Giá trị theo dõi không được rỗng")

    adapter = build_trend_sources(paths, secrets).get(src_name)
    if adapter is None:
        raise HTTPException(status_code=400, detail=f"Nguồn '{src_name}' không tồn tại")
    if kind_name not in adapter.kinds:
        raise HTTPException(
            status_code=400,
            detail=f"Nguồn {src_name} chỉ nhận loại: {', '.join(adapter.kinds)}",
        )
    try:
        if isinstance(adapter, APIFY_SOURCE_CLASSES):
            clean_val = normalize_apify_watch(src_name, kind_name, clean_val)
        elif src_name == "facebook":
            clean_val = normalize_facebook_source(clean_val)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    with get_conn(paths.db_file) as conn:
        conn.execute(
            """
            INSERT INTO watch_items (source, kind, value, enabled, workspace_id)
            VALUES (?, ?, ?, 1, ?)
            ON CONFLICT(source, kind, value) DO UPDATE SET
                enabled = 1,
                workspace_id = excluded.workspace_id
            """,
            (src_name, kind_name, clean_val, ws_id),
        )
        row = conn.execute(
            "SELECT * FROM watch_items WHERE source = ? AND kind = ? AND value = ?",
            (src_name, kind_name, clean_val),
        ).fetchone()
        item_dict = dict(row) if row is not None else {}
        record_audit(
            conn,
            actor="api",
            action="watchlist.upserted",
            object_type="watch_item",
            object_id=int(item_dict.get("id") or 0),
            detail=f"ws={ws_id}, {src_name}/{kind_name}={clean_val}",
        )
    return JSONResponse({"item": item_dict}, status_code=201)


@router.patch("/watchlist/{item_id}")
async def api_v1_patch_watch_item(
    request: Request, item_id: int, body: WatchItemPatchBody
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    existing = query_one(paths.db_file, "SELECT * FROM watch_items WHERE id = ?", (item_id,))
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Watch item #{item_id} not found")
    with get_conn(paths.db_file) as conn:
        conn.execute(
            "UPDATE watch_items SET enabled = ? WHERE id = ?",
            (1 if body.enabled else 0, item_id),
        )
    updated = query_one(paths.db_file, "SELECT * FROM watch_items WHERE id = ?", (item_id,))
    return JSONResponse({"item": updated})


@router.delete("/watchlist/{item_id}")
async def api_v1_delete_watch_item(request: Request, item_id: int) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    existing = query_one(paths.db_file, "SELECT id FROM watch_items WHERE id = ?", (item_id,))
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Watch item #{item_id} not found")
    with get_conn(paths.db_file) as conn:
        conn.execute("DELETE FROM watch_items WHERE id = ?", (item_id,))
    return JSONResponse({"deleted": True, "item_id": item_id})


# ---------- Trends & Pasted Links ----------


def _serialize_trend_item(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "workspace_id": int(row.get("workspace_id") or 1),
        "source": str(row.get("source") or ""),
        "external_id": str(row.get("external_id") or ""),
        "url": str(row.get("url") or ""),
        "title": str(row.get("title") or ""),
        "score": float(row.get("score") or 0.0),
        "metrics": loads_or(row.get("metrics_json"), {}),
        "analysis": loads_or(row.get("analysis_json"), None),
        "analysis_status": str(row.get("analysis_status") or "pending"),
        "analysis_error": row.get("analysis_error"),
        "fetched_at": str(row.get("fetched_at") or ""),
    }


@router.get("/trends")
async def api_v1_list_trends(
    request: Request,
    workspace_id: int | None = Query(default=None),
    source: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    ws_id = resolve_workspace_id(paths.db_file, workspace_id)
    sql = "SELECT * FROM trend_items WHERE workspace_id = ?"
    params: list[Any] = [ws_id]
    if source and source.strip():
        sql += " AND source = ?"
        params.append(source.strip())
    sql += " ORDER BY score DESC, id DESC LIMIT ?"
    params.append(limit)
    rows = query_all(paths.db_file, sql, params)
    return JSONResponse(
        {"trends": [_serialize_trend_item(r) for r in rows], "workspace_id": ws_id}
    )


@router.post("/trends/scan")
async def api_v1_scan_trends(
    request: Request,
    body: TrendScanBody | None = None,
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    ws_id = resolve_workspace_id(
        paths.db_file, body.workspace_id if body else None, require_active=True
    )
    job_id = enqueue_job(
        paths.db_file, "scan_trends", ref_id=0, lane="io", workspace_id=ws_id
    )
    return JSONResponse({"queued": True, "job_id": job_id, "workspace_id": ws_id})


@router.post("/trends/link", status_code=201)
async def api_v1_add_trend_link(
    request: Request, body: TrendLinkBody
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    ws_id = resolve_workspace_id(paths.db_file, body.workspace_id, require_active=True)
    try:
        trend_id, _item = await asyncio.to_thread(
            add_pasted_link, paths, body.url, actor="api"
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    with get_conn(paths.db_file) as conn:
        conn.execute(
            "UPDATE trend_items SET workspace_id = ? WHERE id = ?",
            (ws_id, trend_id),
        )
    row = query_one(paths.db_file, "SELECT * FROM trend_items WHERE id = ?", (trend_id,))
    assert row is not None
    return JSONResponse({"trend": _serialize_trend_item(row)}, status_code=201)


@router.post("/trends/{item_id}/analyse")
async def api_v1_analyse_trend(request: Request, item_id: int) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    row = query_one(paths.db_file, "SELECT id FROM trend_items WHERE id = ?", (item_id,))
    if row is None:
        raise HTTPException(status_code=404, detail=f"Trend item #{item_id} not found")
    job_id = enqueue_trend_analysis(paths, item_id)
    return JSONResponse({"queued": job_id is not None, "job_id": job_id, "item_id": item_id})


# ---------- Suggestions ----------


@router.get("/suggestions")
async def api_v1_list_suggestions(
    request: Request,
    workspace_id: int | None = Query(default=None),
    status: str | None = Query(default=None),
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    ws_id = resolve_workspace_id(paths.db_file, workspace_id)
    sql = "SELECT * FROM suggestions WHERE workspace_id = ?"
    params: list[Any] = [ws_id]
    if status:
        sql += " AND status = ?"
        params.append(status.strip())
    sql += " ORDER BY id DESC LIMIT 100"
    rows = query_all(paths.db_file, sql, params)
    items = [
        {
            **r,
            "formula": loads_or(r.get("formula_json"), {}),
        }
        for r in rows
    ]
    return JSONResponse({"suggestions": items, "workspace_id": ws_id})


@router.post("/suggestions/{suggestion_id}/accept")
async def api_v1_accept_suggestion(
    request: Request,
    suggestion_id: int,
    body: SuggestionAcceptBody | None = None,
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    sug_row = query_one(
        paths.db_file, "SELECT workspace_id FROM suggestions WHERE id = ?", (suggestion_id,)
    )
    if sug_row is None:
        raise HTTPException(status_code=404, detail=f"Suggestion #{suggestion_id} not found")
    ws_id = int((body.workspace_id if body and body.workspace_id is not None else None) or sug_row.get("workspace_id") or 1)
    try:
        job_id = accept_suggestion(
            paths,
            suggestion_id,
            count=body.count if body else 1,
            auto_render=body.auto_render if body else False,
            actor="api",
            render_mode=body.render_mode if body else None,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if job_id is not None:
        with get_conn(paths.db_file) as conn:
            conn.execute(
                "UPDATE jobs SET workspace_id = ? WHERE id = ?",
                (ws_id, int(job_id)),
            )
            conn.execute(
                "UPDATE videos SET workspace_id = ? WHERE suggestion_id = ?",
                (ws_id, suggestion_id),
            )
    return JSONResponse(
        {"accepted": job_id is not None, "job_id": job_id, "suggestion_id": suggestion_id}
    )


@router.post("/suggestions/{suggestion_id}/dismiss")
async def api_v1_dismiss_suggestion(request: Request, suggestion_id: int) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    try:
        ok = dismiss_suggestion(paths.db_file, suggestion_id, actor="api")
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return JSONResponse({"dismissed": ok, "suggestion_id": suggestion_id})

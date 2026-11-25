"""System health, log tail, and Server-Sent Events (SSE) endpoints for `/api/v1`."""
from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from collections import deque
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from videocreator import __version__
from videocreator.api.v1.deps import resolve_workspace_id
from videocreator.db import query_all, query_one
from videocreator.job_store import get_queue_summary, list_jobs
from videocreator.muse_gateway.store import count_active_muse_tasks
from videocreator.paths import AppPaths
from videocreator.workspaces import get_active_workspace_id

router = APIRouter()

NAV_COUNTS_TTL_S = 5.0
_NAV_COUNTS_CACHE: dict[tuple[str, int], tuple[float, dict[str, Any]]] = {}

JOB_KIND_TO_ROUTE: dict[str, str] = {
    "scan_trends": "/trends",
    "trend_scan": "/trends",
    "analyse": "/footage",
    "describe": "/footage",
    "ai_broll": "/characters",
    "plan": "/videos",
    "replan": "/videos",
    "render": "/videos",
    "videogen": "/videos",
    "batch_run": "/batch",
    "workflow_run": "/workflows",
    "localize_extract": "/localize",
    "localize_render": "/localize",
    "news_render": "/news",
    "novel_render": "/novel",
    "podcast_render": "/podcast",
    "editor_render": "/editor",
    "restyle_video": "/video-style",
    "autopilot_tick": "/autopilot",
    "download_model": "/settings",
    "lipsync_render": "/lipsync",
}


def clear_nav_counts_cache() -> None:
    _NAV_COUNTS_CACHE.clear()


def _compute_nav_counts(db_file: Path, ws_id: int) -> dict[str, Any]:
    default_counts: dict[str, Any] = {
        "approvals_pending": 0,
        "suggestions_new": 0,
        "failed_routes": [],
    }
    if not db_file.exists():
        return default_counts
    try:
        r_app = query_one(
            db_file,
            "SELECT COUNT(*) AS c FROM videos WHERE workspace_id = ? AND status = 'pending_approval'",
            (ws_id,),
        )
        r_sug = query_one(
            db_file,
            "SELECT COUNT(*) AS c FROM suggestions WHERE workspace_id = ? AND status IN ('new', 'sent')",
            (ws_id,),
        )
        failed_rows = query_all(
            db_file,
            """
            SELECT DISTINCT kind FROM jobs
            WHERE (workspace_id = ? OR workspace_id IS NULL)
              AND status = 'failed'
              AND COALESCE(finished_at, created_at) >= strftime('%Y-%m-%dT%H:%M:%SZ', 'now', '-24 hours')
            """,
            (ws_id,),
        )
        routes = sorted(
            {
                JOB_KIND_TO_ROUTE[str(row["kind"])]
                for row in failed_rows
                if str(row.get("kind") or "") in JOB_KIND_TO_ROUTE
            }
        )
        return {
            "approvals_pending": int(r_app["c"]) if r_app else 0,
            "suggestions_new": int(r_sug["c"]) if r_sug else 0,
            "failed_routes": routes,
        }
    except sqlite3.Error:
        return default_counts


def get_nav_counts(
    db_file: Path,
    *,
    ws_id: int,
    use_cache: bool = True,
    ttl_s: float = NAV_COUNTS_TTL_S,
) -> dict[str, Any]:
    cache_key = (str(db_file), int(ws_id))
    now = time.monotonic()
    if use_cache:
        cached = _NAV_COUNTS_CACHE.get(cache_key)
        if cached is not None and now < cached[0]:
            return cached[1]
    fresh = _compute_nav_counts(db_file, ws_id)
    _NAV_COUNTS_CACHE[cache_key] = (now + ttl_s, fresh)
    return fresh


def _read_log_tail(log_file: Path, max_lines: int) -> list[str]:
    if not log_file.exists():
        return []
    with log_file.open("r", encoding="utf-8", errors="replace") as fh:
        tail = deque(fh, maxlen=max_lines)
    return [line.rstrip("\r\n") for line in tail]


def _build_snapshot(
    paths: AppPaths,
    *,
    workspace_id: int | None = None,
    use_nav_cache: bool = True,
) -> dict[str, Any]:
    active_ws = get_active_workspace_id(paths.db_file)
    effective_ws = resolve_workspace_id(paths.db_file, workspace_id) if workspace_id is not None else active_ws
    return {
        "active_workspace_id": active_ws,
        "queue": get_queue_summary(paths.db_file, workspace_id=workspace_id),
        "muse_queue": count_active_muse_tasks(paths.db_file, workspace_id=workspace_id),
        "recent_jobs": list_jobs(paths.db_file, workspace_id=workspace_id, limit=15),
        "nav_counts": get_nav_counts(
            paths.db_file, ws_id=effective_ws, use_cache=use_nav_cache
        ),
    }


@router.get("/health")
async def api_health(request: Request) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    return JSONResponse(
        {
            "status": "ok",
            "version": __version__,
            "api_version": "v1",
            "active_workspace_id": get_active_workspace_id(paths.db_file),
        }
    )


@router.get("/logs/tail")
async def api_logs_tail(
    request: Request,
    lines: int = Query(default=100, ge=1, le=2000),
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    entries = _read_log_tail(paths.log_file, lines)
    return JSONResponse(
        {
            "lines": entries,
            "count": len(entries),
            "path": str(paths.log_file),
        }
    )


@router.get("/events")
async def api_events(
    request: Request,
    once: bool = Query(default=False),
    workspace_id: int | None = Query(default=None),
) -> StreamingResponse:
    paths: AppPaths = request.app.state.paths

    async def _stream() -> AsyncIterator[str]:
        try:
            while True:
                payload = json.dumps(
                    _build_snapshot(
                        paths,
                        workspace_id=workspace_id,
                        use_nav_cache=not once,
                    ),
                    ensure_ascii=False,
                )
                yield f"event: queue_snapshot\ndata: {payload}\n\n"
                if once or await request.is_disconnected():
                    break
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            return

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )

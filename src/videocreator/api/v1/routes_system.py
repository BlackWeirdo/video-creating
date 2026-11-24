"""System health, log tail, and Server-Sent Events (SSE) endpoints for `/api/v1`."""
from __future__ import annotations

import asyncio
import json
from collections import deque
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from videocreator import __version__
from videocreator.job_store import get_queue_summary, list_jobs
from videocreator.paths import AppPaths
from videocreator.workspaces import get_active_workspace_id

router = APIRouter()


def _read_log_tail(log_file: Path, max_lines: int) -> list[str]:
    if not log_file.exists():
        return []
    with log_file.open("r", encoding="utf-8", errors="replace") as fh:
        tail = deque(fh, maxlen=max_lines)
    return [line.rstrip("\r\n") for line in tail]


def _build_snapshot(
    paths: AppPaths, *, workspace_id: int | None = None
) -> dict[str, Any]:
    return {
        "active_workspace_id": get_active_workspace_id(paths.db_file),
        "queue": get_queue_summary(paths.db_file, workspace_id=workspace_id),
        "recent_jobs": list_jobs(paths.db_file, workspace_id=workspace_id, limit=15),
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
                    _build_snapshot(paths, workspace_id=workspace_id),
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

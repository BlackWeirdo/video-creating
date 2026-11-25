"""AI routing dashboard, CLI health check, and quota provider wake endpoints for `/api/v1`."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from videocreator.ai.cli_base import find_claude_binary
from videocreator.ai.quota import clear_provider_rest
from videocreator.db import get_conn, query_all, record_audit
from videocreator.paths import AppPaths
from videocreator.services.ai_cli_health import check_claude_cli_health

router = APIRouter()


@router.get("/ai/routes")
async def api_v1_ai_routes(request: Request) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    provider_states = query_all(
        paths.db_file,
        "SELECT name, resting_until, last_error FROM provider_state ORDER BY name",
    )
    waiting_jobs = query_all(
        paths.db_file,
        "SELECT * FROM jobs WHERE status = 'waiting_quota' ORDER BY id ASC",
    )
    recent_usage = query_all(
        paths.db_file,
        "SELECT * FROM ai_usage ORDER BY id DESC LIMIT 25",
    )
    return JSONResponse(
        {
            "provider_states": provider_states,
            "waiting_jobs": waiting_jobs,
            "recent_usage": recent_usage,
            "cli_binary": find_claude_binary(),
        }
    )


@router.post("/ai/check-cli")
async def api_v1_check_cli(request: Request) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    info = await asyncio.to_thread(check_claude_cli_health, paths.db_file)
    return JSONResponse(info)


@router.post("/ai/providers/{provider_name}/wake")
async def api_v1_wake_provider(request: Request, provider_name: str) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    clear_provider_rest(paths.db_file, provider_name)
    with get_conn(paths.db_file) as conn:
        cur = conn.execute(
            """
            UPDATE jobs
            SET status = 'queued', error = NULL
            WHERE status = 'waiting_quota'
            """
        )
        requeued = int(cur.rowcount or 0)
        record_audit(
            conn,
            actor="api",
            action="ai.wake_provider",
            object_type="provider",
            detail=provider_name,
        )
    return JSONResponse(
        {"woken": True, "provider": provider_name, "requeued_jobs": requeued}
    )


__all__ = ["router"]

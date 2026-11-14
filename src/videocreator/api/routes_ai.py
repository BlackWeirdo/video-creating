"""Routes for AI subscription CLI health check, quota recovery, and routing dashboard (Phase 18)."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from videocreator import __version__
from videocreator.ai.cli_base import find_claude_binary
from videocreator.ai.quota import clear_provider_rest, mark_provider_error
from videocreator.config import load_settings
from videocreator.db import get_conn, query_all, query_one, record_audit
from videocreator.paths import AppPaths

router = APIRouter()


def check_claude_cli_health(db_file: Path) -> dict[str, Any]:
    """Checks whether `claude.exe` is installed and accessible on the host machine."""
    binary = find_claude_binary()
    if not binary:
        msg = "Không tìm thấy claude.exe trên máy. Hãy cài @anthropic-ai/claude-code và chạy `claude login`."
        mark_provider_error(db_file, "claude_cli", msg)
        return {"ok": False, "binary": None, "version": None, "message": msg}

    try:
        proc = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
        )
        version_str = (proc.stdout or proc.stderr).strip()
        if proc.returncode == 0 and version_str:
            clear_provider_rest(db_file, "claude_cli")
            return {
                "ok": True,
                "binary": binary,
                "version": version_str,
                "message": f"Sẵn sàng: {version_str} ({binary})",
            }
        err = f"claude --version trả mã {proc.returncode}: {version_str}"
        mark_provider_error(db_file, "claude_cli", err)
        return {"ok": False, "binary": binary, "version": None, "message": err}
    except Exception as exc:
        err = f"Lỗi kiểm tra claude.exe: {exc}"
        mark_provider_error(db_file, "claude_cli", err)
        return {"ok": False, "binary": binary, "version": None, "message": err}


@router.get("/ai-routes", response_class=HTMLResponse)
async def ai_routes_page(
    request: Request,
    msg: str | None = None,
    cli_status: str | None = None,
) -> HTMLResponse:
    paths: AppPaths = request.app.state.paths
    cfg = load_settings(paths.config_file)
    templates = Jinja2Templates(directory=str(paths.templates_dir))

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

    return templates.TemplateResponse(
        request,
        "ai_routes.html",
        {
            "page": "settings",
            "settings": cfg,
            "provider_states": provider_states,
            "waiting_jobs": waiting_jobs,
            "recent_usage": recent_usage,
            "cli_binary": find_claude_binary(),
            "msg": msg,
            "cli_status": cli_status,
            "version": __version__,
        },
    )


@router.post("/ai/check-cli")
async def trigger_check_cli(request: Request) -> RedirectResponse:
    paths: AppPaths = request.app.state.paths
    info = check_claude_cli_health(paths.db_file)
    status_code = "ok" if info["ok"] else "error"
    return RedirectResponse(
        url=f"/ai-routes?msg=cli_checked&cli_status={status_code}",
        status_code=303,
    )


@router.post("/ai/provider/{provider_name}/wake")
async def wake_provider(request: Request, provider_name: str) -> RedirectResponse:
    paths: AppPaths = request.app.state.paths
    clear_provider_rest(paths.db_file, provider_name)
    with get_conn(paths.db_file) as conn:
        conn.execute(
            """
            UPDATE jobs
            SET status = 'queued', error = NULL
            WHERE status = 'waiting_quota'
            """
        )
        record_audit(
            conn,
            actor="ui",
            action="ai.wake_provider",
            object_type="provider",
            detail=provider_name,
        )
    return RedirectResponse(url="/ai-routes?msg=provider_woken", status_code=303)

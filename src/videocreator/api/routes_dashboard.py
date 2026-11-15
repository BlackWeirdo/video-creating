"""Health check and dashboard page."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from videocreator import __version__
from videocreator.config import Settings, load_settings
from videocreator.db import query_all
from videocreator.paths import AppPaths
from videocreator.templating import get_templates

router = APIRouter()

FOOTAGE_STATUSES: tuple[str, ...] = ("imported", "analysing", "analysed", "failed")


VIDEO_STATUSES: tuple[str, ...] = (
    "planned",
    "rendering",
    "rendered",
    "scoring",
    "pending_approval",
    "approved",
    "scheduled",
    "posted",
    "failed",
    "rejected",
    "superseded",
)


def _collect_dashboard_stats(db_file: Path, settings: Settings) -> dict[str, Any]:
    footage_counts = {s: 0 for s in FOOTAGE_STATUSES}
    for row in query_all(
        db_file, "SELECT status, COUNT(*) AS cnt FROM footage GROUP BY status"
    ):
        footage_counts[str(row["status"])] = int(row["cnt"])

    video_counts = {s: 0 for s in VIDEO_STATUSES}
    for row in query_all(
        db_file, "SELECT status, COUNT(*) AS cnt FROM videos GROUP BY status"
    ):
        video_counts[str(row["status"])] = int(row["cnt"])

    job_counts: dict[str, int] = {
        "queued": 0,
        "running": 0,
        "waiting_quota": 0,
        "done": 0,
        "failed": 0,
    }
    for row in query_all(
        db_file, "SELECT status, COUNT(*) AS cnt FROM jobs GROUP BY status"
    ):
        job_counts[str(row["status"])] = int(row["cnt"])

    recent_jobs = query_all(
        db_file,
        """
        SELECT id, kind, ref_id, status, error, created_at, started_at, finished_at
        FROM jobs
        ORDER BY id DESC
        LIMIT 10
        """,
    )

    today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    usage_rows = query_all(
        db_file,
        """
        SELECT route, kind, COUNT(*) AS calls, COALESCE(SUM(cost_usd), 0.0) AS cost_usd
        FROM ai_usage
        WHERE day = ?
        GROUP BY route, kind
        """,
        (today_utc,),
    )
    sub_calls = 0
    api_calls = 0
    text_api_cost = 0.0
    gen_api_cost = 0.0
    studio_api_cost = 0.0
    for r in usage_rows:
        route = str(r["route"])
        kind = str(r["kind"])
        calls = int(r["calls"])
        cost = float(r["cost_usd"])
        if route == "subscription":
            sub_calls += calls
        elif route == "api":
            api_calls += calls
            if kind == "videogen":
                gen_api_cost += cost
            elif kind == "studio":
                studio_api_cost += cost
            else:
                text_api_cost += cost

    provider_states = query_all(
        db_file, "SELECT name, resting_until, last_error FROM provider_state ORDER BY name"
    )

    return {
        "footage_counts": footage_counts,
        "video_counts": video_counts,
        "job_counts": job_counts,
        "recent_jobs": recent_jobs,
        "ai_today": {
            "day": today_utc,
            "subscription_calls": sub_calls,
            "api_calls": api_calls,
            "text_api_cost_usd": round(text_api_cost, 4),
            "generative_api_cost_usd": round(gen_api_cost, 4),
            "studio_api_cost_usd": round(studio_api_cost, 4),
            "daily_limit_usd": settings.budget.daily_usd,
            "generative_limit_usd": settings.budget.generative_daily_usd,
            "studio_limit_usd": settings.budget.studio_daily_usd,
        },
        "provider_states": provider_states,
    }


@router.get("/health")
async def health(request: Request) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    cfg = load_settings(paths.config_file)
    return JSONResponse(
        {
            "status": "ok",
            "role": cfg.role,
            "version": __version__,
        }
    )


@router.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    paths: AppPaths = request.app.state.paths
    templates = get_templates(paths)
    cfg = load_settings(paths.config_file)
    stats = _collect_dashboard_stats(paths.db_file, cfg)
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "page": "home",
            "settings": cfg,
            "stats": stats,
            "version": __version__,
        },
    )

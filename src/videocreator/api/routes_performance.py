"""Post performance page and manual metrics collection."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from videocreator import __version__
from videocreator.config import load_settings
from videocreator.paths import AppPaths
from videocreator.templating import get_templates

router = APIRouter()


@router.get("/performance", response_class=HTMLResponse)
async def performance_page(
    request: Request,
    msg: str | None = None,
) -> HTMLResponse:
    from videocreator.posting.performance import list_performance_rows
    from videocreator.reports import weekly_summary

    paths: AppPaths = request.app.state.paths
    cfg = load_settings(paths.config_file)
    templates = get_templates(paths)
    rows = list_performance_rows(paths.db_file)
    summary_text = weekly_summary(paths)

    return templates.TemplateResponse(
        request,
        "performance.html",
        {
            "page": "performance",
            "settings": cfg,
            "rows": rows,
            "weekly_summary_text": summary_text,
            "msg": msg,
            "version": __version__,
        },
    )


@router.post("/performance/collect")
async def collect_metrics_now_route(request: Request) -> RedirectResponse:
    from videocreator.posting.metrics import collect_due_metrics

    paths: AppPaths = request.app.state.paths
    count = await asyncio.to_thread(collect_due_metrics, paths)
    return RedirectResponse(url=f"/performance?msg=collected_{count}", status_code=303)

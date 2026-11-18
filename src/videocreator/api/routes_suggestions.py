"""Trend suggestion routes: list, accept, dismiss."""
from __future__ import annotations
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from videocreator import __version__
from videocreator.config import load_settings
from videocreator.db import query_all
from videocreator.jsonutil import loads_or
from videocreator.paths import AppPaths
from videocreator.templating import get_templates
from videocreator.trends.suggestion_actions import accept_suggestion, dismiss_suggestion

router = APIRouter()


@router.get("/suggestions", response_class=HTMLResponse)
async def suggestions_page(
    request: Request,
    msg: str | None = None,
) -> HTMLResponse:
    paths: AppPaths = request.app.state.paths
    cfg = load_settings(paths.config_file)
    templates = get_templates(paths)

    rows = query_all(
        paths.db_file,
        """
        SELECT s.*, t.source, t.author, t.url AS ref_url, t.score, t.analysis_json
        FROM suggestions s
        LEFT JOIN trend_items t ON s.trend_item_id = t.id
        ORDER BY s.id DESC
        """,
    )
    suggestions = []
    for r in rows:
        formula = loads_or(r.get("formula_json"), {})
        analysis = loads_or(r.get("analysis_json"), {})
        suggestions.append({**r, "formula": formula, "analysis": analysis if isinstance(analysis, dict) else {}})

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
    auto_render: bool = Form(True),
) -> RedirectResponse:
    paths: AppPaths = request.app.state.paths
    job_id = accept_suggestion(paths, suggestion_id, count=count, auto_render=auto_render, actor="ui")
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

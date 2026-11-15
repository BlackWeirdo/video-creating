"""Routes for Studio Mode (`/studio`): sessions run as queued `studio` jobs (Phase 17)."""
from __future__ import annotations

import json
import shutil
from typing import Any

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from videocreator import __version__
from videocreator.ai.budget import get_daily_api_spend
from videocreator.config import load_settings
from videocreator.db import query_all
from videocreator.paths import AppPaths
from videocreator.studio.session import (
    StudioBusyError,
    confirm_studio_plan,
    create_studio_session,
    enqueue_studio_job,
    list_studio_sessions,
    request_studio_revision,
)
from videocreator.studio.templates import (
    list_studio_templates,
    save_studio_template,
    start_render_from_template,
)
from videocreator.templating import get_templates

router = APIRouter()


def _audio_options(voice_lang: str, music_asset_id: str, sfx_asset_id: str) -> dict[str, Any]:
    return {
        "voice_lang": voice_lang if voice_lang in ("vi", "en") else "none",
        "music_asset_id": int(music_asset_id) if music_asset_id.isdigit() else None,
        "sfx_asset_id": int(sfx_asset_id) if sfx_asset_id.isdigit() else None,
    }


def _pending_plan(paths: AppPaths, session: dict[str, Any]) -> list[dict[str, Any]]:
    """Script rows shown at the confirmation stop (`FR-STD-05`), read from the video's plan."""
    if session["status"] != "awaiting_confirm":
        return []
    rows = query_all(
        paths.db_file,
        "SELECT v.plan_json FROM videos v WHERE v.id = ?",
        (session["video_id"],),
    )
    try:
        plan = json.loads(rows[0]["plan_json"]) if rows else {}
    except ValueError:
        plan = {}
    shots = {int(r["id"]): r for r in query_all(paths.db_file, "SELECT id, description FROM shots")}
    return [
        {**s, "description": (shots.get(int(s["shot_id"])) or {}).get("description") or ""}
        for s in plan.get("shots") or []
    ]


@router.get("/studio", response_class=HTMLResponse)
async def studio_page(
    request: Request,
    msg: str | None = None,
) -> HTMLResponse:
    paths: AppPaths = request.app.state.paths
    cfg = load_settings(paths.config_file)
    templates = get_templates(paths)

    sessions = list_studio_sessions(paths.db_file)
    for s in sessions:
        s["plan_rows"] = _pending_plan(paths, s)
    assets = query_all(paths.db_file, "SELECT id, kind, path FROM assets WHERE kind IN ('music', 'sfx') ORDER BY id DESC")

    return templates.TemplateResponse(
        request,
        "studio.html",
        {
            "page": "studio",
            "settings": cfg,
            "sessions": sessions,
            "templates": list_studio_templates(paths.db_file),
            "shots": query_all(paths.db_file, "SELECT id, description, has_product FROM shots ORDER BY id DESC LIMIT 40"),
            "music_assets": [a for a in assets if a["kind"] == "music"],
            "sfx_assets": [a for a in assets if a["kind"] == "sfx"],
            "studio_spent": get_daily_api_spend(paths.db_file, bucket="studio"),
            "node_available": shutil.which("node") is not None,
            "msg": msg,
            "version": __version__,
        },
    )


@router.post("/studio/create")
async def create_studio_session_route(
    request: Request,
    prompt: str = Form(...),
    voice_lang: str = Form("none"),
    music_asset_id: str = Form(""),
    sfx_asset_id: str = Form(""),
    auto_run: bool = Form(False),
) -> RedirectResponse:
    paths: AppPaths = request.app.state.paths
    options = {**_audio_options(voice_lang, music_asset_id, sfx_asset_id), "auto_run": auto_run}
    try:
        sid = create_studio_session(paths, prompt=prompt.strip(), options=options)
    except (StudioBusyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    enqueue_studio_job(paths.db_file, sid)
    return RedirectResponse(url=f"/studio?msg=session_{sid}_queued", status_code=303)


@router.post("/studio/{session_id}/confirm")
async def confirm_studio_plan_route(request: Request, session_id: int) -> RedirectResponse:
    paths: AppPaths = request.app.state.paths
    try:
        confirm_studio_plan(paths, session_id)
    except (StudioBusyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(url=f"/studio?msg=confirmed_{session_id}", status_code=303)


@router.post("/studio/{session_id}/revise")
async def revise_studio_session_route(
    request: Request,
    session_id: int,
    prompt: str = Form(...),
) -> RedirectResponse:
    paths: AppPaths = request.app.state.paths
    try:
        request_studio_revision(paths, session_id, prompt)
    except (StudioBusyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(url=f"/studio?msg=revision_{session_id}_queued", status_code=303)


@router.post("/studio/{session_id}/save-template")
async def save_studio_template_route(
    request: Request,
    session_id: int,
    name: str = Form(...),
) -> RedirectResponse:
    paths: AppPaths = request.app.state.paths
    try:
        tid = save_studio_template(paths, session_id, name=name.strip())
    except (LookupError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(url=f"/studio?msg=template_{tid}", status_code=303)


@router.post("/studio/templates/{template_id}/render")
async def render_from_template_route(
    request: Request,
    template_id: int,
    shot_ids: list[int] = Form(default=[]),
    subtitles: str = Form(""),
    title: str = Form(""),
    voice_lang: str = Form("none"),
    music_asset_id: str = Form(""),
    sfx_asset_id: str = Form(""),
) -> RedirectResponse:
    paths: AppPaths = request.app.state.paths
    try:
        sid = start_render_from_template(
            paths,
            template_id,
            shot_ids=shot_ids,
            subtitles=[line.strip() for line in subtitles.splitlines()],
            title=title.strip() or None,
            options=_audio_options(voice_lang, music_asset_id, sfx_asset_id),
        )
    except (StudioBusyError, LookupError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(url=f"/studio?msg=session_{sid}_queued", status_code=303)

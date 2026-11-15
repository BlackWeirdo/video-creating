"""Account connection, post scheduling, publishing history, and manual bundle download routes (Phase 07)."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from videocreator import __version__
from videocreator.config import load_settings
from videocreator.db import query_all
from videocreator.paths import AppPaths
from videocreator.posting.captions import build_manual_bundle_zip
from videocreator.posting.post_actions import (
    cancel_scheduled_post,
    confirm_user_action_post,
    reschedule_post,
    retry_failed_post,
)
from videocreator.posting.publish import publish_due_posts
from videocreator.posting.service import is_posting_paused, schedule_approved_video, set_posting_paused
from videocreator.templating import get_templates
from videocreator.timeutil import utc_now_iso

router = APIRouter()


@router.get("/schedule", response_class=HTMLResponse)
async def schedule_page(
    request: Request,
    msg: str | None = None,
) -> HTMLResponse:
    paths: AppPaths = request.app.state.paths
    cfg = load_settings(paths.config_file)
    templates = get_templates(paths)

    approved_videos = query_all(
        paths.db_file,
        "SELECT * FROM videos WHERE status IN ('approved', 'scheduled', 'posted', 'failed') ORDER BY id DESC",
    )
    accounts = query_all(
        paths.db_file,
        "SELECT * FROM accounts WHERE enabled = 1 ORDER BY platform, id ASC",
    )
    posts = query_all(
        paths.db_file,
        """
        SELECT p.*, a.platform, a.name AS account_name, a.lang
        FROM posts p
        JOIN accounts a ON p.account_id = a.id
        ORDER BY p.scheduled_at DESC, p.id DESC
        """,
    )
    paused = is_posting_paused(paths.db_file)

    return templates.TemplateResponse(
        request,
        "posts.html",
        {
            "page": "schedule",
            "settings": cfg,
            "approved_videos": approved_videos,
            "accounts": accounts,
            "posts": posts,
            "posting_paused": paused,
            "msg": msg,
            "version": __version__,
        },
    )


@router.post("/schedule/toggle-pause")
async def toggle_pause_route(request: Request) -> RedirectResponse:
    paths: AppPaths = request.app.state.paths
    cur = is_posting_paused(paths.db_file)
    set_posting_paused(paths.db_file, not cur, actor="ui")
    return RedirectResponse(url="/schedule?msg=pause_toggled", status_code=303)


@router.post("/posts/{post_id}/retry")
async def retry_post_route(request: Request, post_id: int) -> RedirectResponse:
    paths: AppPaths = request.app.state.paths
    retry_failed_post(paths.db_file, post_id, actor="ui")
    return RedirectResponse(url="/schedule?msg=retried", status_code=303)


@router.post("/posts/{post_id}/reschedule")
async def reschedule_post_route(
    request: Request,
    post_id: int,
    scheduled_at: str = Form(...),
) -> RedirectResponse:
    paths: AppPaths = request.app.state.paths
    reschedule_post(paths.db_file, post_id, scheduled_at.strip(), actor="ui")
    return RedirectResponse(url="/schedule?msg=rescheduled", status_code=303)


@router.post("/posts/{post_id}/cancel")
async def cancel_post_route(request: Request, post_id: int) -> RedirectResponse:
    paths: AppPaths = request.app.state.paths
    cancel_scheduled_post(paths.db_file, post_id, actor="ui")
    return RedirectResponse(url="/schedule?msg=cancelled", status_code=303)


@router.post("/posts/{post_id}/confirm-posted")
async def confirm_posted_route(
    request: Request,
    post_id: int,
    permalink: str = Form(""),
) -> RedirectResponse:
    paths: AppPaths = request.app.state.paths
    confirm_user_action_post(
        paths.db_file,
        post_id,
        permalink=permalink.strip() or None,
        actor="ui",
    )
    return RedirectResponse(url="/schedule?msg=confirmed_posted", status_code=303)


@router.post("/videos/{video_id}/schedule")
async def schedule_or_post_video(
    request: Request,
    video_id: int,
    account_ids: list[int] = Form(default=[]),
    scheduled_at: str = Form(""),
    post_now: bool = Form(False),
) -> RedirectResponse:
    paths: AppPaths = request.app.state.paths
    sched_iso = utc_now_iso() if post_now or not scheduled_at.strip() else scheduled_at.strip()
    try:
        schedule_approved_video(
            paths.db_file,
            video_id,
            account_ids=account_ids,
            scheduled_at_iso=sched_iso,
            actor="ui",
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if post_now:
        await asyncio.to_thread(publish_due_posts, paths)
        return RedirectResponse(url="/schedule?msg=posted_now", status_code=303)

    return RedirectResponse(url="/schedule?msg=scheduled", status_code=303)


@router.get("/videos/{video_id}/manual-bundle")
async def download_manual_bundle(request: Request, video_id: int) -> FileResponse:
    paths: AppPaths = request.app.state.paths
    try:
        zip_path = await asyncio.to_thread(build_manual_bundle_zip, paths, video_id)
    except (LookupError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=f"video_{video_id}_manual_bundle.zip",
    )

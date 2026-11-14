"""Approval queue UI routes (`GET /approval`, `POST /videos/{id}/approve`, `POST /videos/{id}/reject`, Phase 06)."""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from videocreator import __version__
from videocreator.approvals import approve, list_pending_approval_videos, redo_video, reject
from videocreator.config import load_settings
from videocreator.db import get_conn, query_all, query_one, record_audit
from videocreator.paths import AppPaths
from videocreator.pipeline.planner import PLATFORM_CHAR_LIMITS, PLATFORM_HASHTAG_LIMITS
from videocreator.state import InvalidTransitionError

router = APIRouter()


@router.get("/approval", response_class=HTMLResponse)
async def approval_page(
    request: Request,
    msg: str | None = None,
) -> HTMLResponse:
    paths: AppPaths = request.app.state.paths
    cfg = load_settings(paths.config_file)
    templates = Jinja2Templates(directory=str(paths.templates_dir))

    pending = list_pending_approval_videos(paths.db_file)
    recent_decided = query_all(
        paths.db_file,
        """
        SELECT id, status, approved_by, approved_at, reject_reason
        FROM videos
        WHERE status IN ('approved', 'rejected', 'scheduled', 'posted')
        ORDER BY id DESC
        LIMIT 10
        """,
    )
    accounts = query_all(
        paths.db_file,
        "SELECT id, platform, name, lang FROM accounts WHERE enabled = 1 ORDER BY platform, id",
    )

    return templates.TemplateResponse(
        request,
        "approval.html",
        {
            "page": "approval",
            "settings": cfg,
            "pending_videos": pending,
            "recent_decided": recent_decided,
            "accounts": accounts,
            "msg": msg,
            "version": __version__,
        },
    )


def _update_captions_from_form(
    paths: AppPaths,
    video_id: int,
    form: Any,
) -> None:
    row = query_one(paths.db_file, "SELECT plan_json FROM videos WHERE id = ?", (video_id,))
    if row is None:
        return
    try:
        plan = json.loads(row.get("plan_json") or "{}")
    except Exception:
        plan = {}

    captions = plan.get("captions") or {}
    changed = False
    for platform in ("facebook", "instagram", "threads", "tiktok"):
        cap_text = form.get(f"caption_{platform}_text")
        cap_tags = form.get(f"caption_{platform}_hashtags")
        if cap_text is not None or cap_tags is not None:
            max_chars = PLATFORM_CHAR_LIMITS[platform]
            max_tags = PLATFORM_HASHTAG_LIMITS[platform]
            raw_tags = str(cap_tags or "").replace(",", " ").split()
            clean_tags = []
            for t in raw_tags:
                tag = t.strip()
                if not tag:
                    continue
                if not tag.startswith("#"):
                    tag = f"#{tag}"
                clean_tags.append(tag)
                if len(clean_tags) >= max_tags:
                    break
            captions[platform] = {
                "text": str(cap_text or "").strip()[:max_chars],
                "hashtags": clean_tags,
            }
            changed = True

    if changed:
        plan["captions"] = captions
        with get_conn(paths.db_file) as conn:
            conn.execute(
                "UPDATE videos SET plan_json = ?, captions_json = ? WHERE id = ?",
                (
                    json.dumps(plan, ensure_ascii=False),
                    json.dumps(captions, ensure_ascii=False),
                    video_id,
                ),
            )


@router.post("/videos/{video_id}/approve")
async def approve_video_route(
    request: Request,
    video_id: int,
) -> RedirectResponse:
    paths: AppPaths = request.app.state.paths
    form = await request.form()
    _update_captions_from_form(paths, video_id, form)

    account_ids = [int(x) for x in form.getlist("account_ids") if str(x).isdigit()]
    try:
        won = approve(
            paths.db_file,
            video_id,
            by="ui",
            target_account_ids=account_ids if account_ids else None,
            config_file=paths.config_file,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    msg_key = "approved" if won else "already_decided"
    return RedirectResponse(url=f"/approval?msg={msg_key}", status_code=303)


@router.post("/videos/{video_id}/reject")
async def reject_video_route(
    request: Request,
    video_id: int,
    reason: str = Form(""),
) -> RedirectResponse:
    paths: AppPaths = request.app.state.paths
    try:
        won = reject(paths.db_file, video_id, by="ui", reason=reason)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    msg_key = "rejected" if won else "already_decided"
    return RedirectResponse(url=f"/approval?msg={msg_key}", status_code=303)


@router.post("/videos/{video_id}/redo")
async def redo_video_route(
    request: Request,
    video_id: int,
) -> RedirectResponse:
    paths: AppPaths = request.app.state.paths
    try:
        new_vid = redo_video(paths.db_file, video_id, by="ui")
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    msg_key = "redone" if new_vid is not None else "redo_limit"
    return RedirectResponse(url=f"/approval?msg={msg_key}", status_code=303)


@router.post("/videos/{video_id}/cover")
async def upload_cover_route(
    request: Request,
    video_id: int,
    file: UploadFile = File(...),
) -> RedirectResponse:
    paths: AppPaths = request.app.state.paths
    row = query_one(paths.db_file, "SELECT id FROM videos WHERE id = ?", (video_id,))
    if row is None:
        raise HTTPException(status_code=404, detail=f"Video #{video_id} not found")
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty cover image file")
    rel_cover = f"output/cover_{video_id}.jpg"
    abs_cover = paths.media_dir / rel_cover
    abs_cover.parent.mkdir(parents=True, exist_ok=True)
    abs_cover.write_bytes(raw)
    with get_conn(paths.db_file) as conn:
        conn.execute("UPDATE videos SET cover_path = ? WHERE id = ?", (rel_cover, video_id))
    return RedirectResponse(url="/approval?msg=cover_saved", status_code=303)

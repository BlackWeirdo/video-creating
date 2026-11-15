"""Routes for the Manual Subscription Workstation (`/manual`) (Phase 14 & 18)."""
from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from videocreator import __version__
from videocreator.config import load_settings
from videocreator.db import get_conn, query_all
from videocreator.manual.fulfill import fulfill_manual_ticket
from videocreator.manual.tickets import create_manual_ticket, scan_inbox_for_tickets
from videocreator.paths import AppPaths
from videocreator.templating import get_templates

router = APIRouter()


@router.get("/manual", response_class=HTMLResponse)
async def manual_page(
    request: Request,
    msg: str | None = None,
) -> HTMLResponse:
    paths: AppPaths = request.app.state.paths
    cfg = load_settings(paths.config_file)
    templates = get_templates(paths)
    scan_inbox_for_tickets(paths)
    tickets = query_all(
        paths.db_file,
        "SELECT * FROM manual_tickets ORDER BY id DESC LIMIT 40",
    )
    return templates.TemplateResponse(
        request,
        "manual.html",
        {
            "page": "broll",
            "settings": cfg,
            "tickets": tickets,
            "msg": msg,
            "version": __version__,
        },
    )


@router.post("/manual/create")
async def create_ticket_route(
    request: Request,
    prompt: str = Form(...),
    seconds: int = Form(6),
) -> RedirectResponse:
    paths: AppPaths = request.app.state.paths
    tid = create_manual_ticket(paths, prompt=prompt, seconds=seconds)
    return RedirectResponse(url=f"/manual?msg=created_{tid}", status_code=303)


@router.post("/manual/{ticket_id}/upload")
async def upload_ticket_video_route(
    request: Request,
    ticket_id: int,
    file: UploadFile = File(...),
) -> RedirectResponse:
    paths: AppPaths = request.app.state.paths
    suffix = Path(file.filename or "clip.mp4").suffix or ".mp4"
    tmp_file = paths.work_dir / f"manual_upload_{ticket_id}{suffix}"
    tmp_file.parent.mkdir(parents=True, exist_ok=True)
    with tmp_file.open("wb") as out:
        await asyncio.to_thread(shutil.copyfileobj, file.file, out)
    try:
        _aid, sid = await asyncio.to_thread(fulfill_manual_ticket, paths, ticket_id, tmp_file, actor="ui")
    except Exception as exc:
        tmp_file.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    tmp_file.unlink(missing_ok=True)
    return RedirectResponse(url=f"/manual?msg=fulfilled_shot_{sid}", status_code=303)


@router.post("/manual/{ticket_id}/cancel")
async def cancel_ticket_route(
    request: Request,
    ticket_id: int,
) -> RedirectResponse:
    paths: AppPaths = request.app.state.paths
    with get_conn(paths.db_file) as conn:
        conn.execute(
            """
            UPDATE manual_tickets
            SET status = 'cancelled',
                closed_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
            WHERE id = ? AND status = 'open'
            """,
            (ticket_id,),
        )
    return RedirectResponse(url="/manual?msg=cancelled", status_code=303)

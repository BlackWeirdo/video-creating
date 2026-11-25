"""Manual Subscription Workstation ticket endpoints (`/api/v1/manual-tickets`)."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from videocreator.api.v1.uploads import MAX_FOOTAGE_UPLOAD_BYTES, save_upload_to_temp
from videocreator.db import get_conn, query_all, query_one
from videocreator.manual.fulfill import ALLOWED_VIDEO_EXTS, fulfill_manual_ticket
from videocreator.manual.tickets import create_manual_ticket, scan_inbox_for_tickets
from videocreator.paths import AppPaths

router = APIRouter()


class ManualTicketCreateBody(BaseModel):
    prompt: str
    kind: str = "broll"
    seconds: int = 6


@router.get("/manual-tickets")
async def api_v1_list_manual_tickets(request: Request) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    await asyncio.to_thread(scan_inbox_for_tickets, paths)
    tickets = query_all(
        paths.db_file,
        "SELECT * FROM manual_tickets ORDER BY id DESC LIMIT 60",
    )
    return JSONResponse({"tickets": tickets})


@router.post("/manual-tickets", status_code=201)
async def api_v1_create_manual_ticket(
    request: Request, body: ManualTicketCreateBody
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    try:
        tid = create_manual_ticket(
            paths,
            prompt=body.prompt,
            kind=body.kind,
            seconds=max(4, min(10, int(body.seconds))),
            actor="api",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    ticket = query_one(paths.db_file, "SELECT * FROM manual_tickets WHERE id = ?", (tid,))
    return JSONResponse({"ticket": ticket, "ticket_id": tid}, status_code=201)


@router.post("/manual-tickets/{ticket_id}/upload")
async def api_v1_upload_manual_ticket(
    request: Request,
    ticket_id: int,
    file: UploadFile = File(...),
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    tmp_file = await save_upload_to_temp(
        file,
        paths.work_dir,
        allowed_extensions=ALLOWED_VIDEO_EXTS,
        default_ext=".mp4",
        max_bytes=MAX_FOOTAGE_UPLOAD_BYTES,
        prefix=f"manual_ticket_{ticket_id}",
    )
    try:
        asset_id, shot_id = await asyncio.to_thread(
            fulfill_manual_ticket, paths, ticket_id, tmp_file, actor="api"
        )
    except (LookupError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        tmp_file.unlink(missing_ok=True)
    ticket = query_one(paths.db_file, "SELECT * FROM manual_tickets WHERE id = ?", (ticket_id,))
    return JSONResponse(
        {
            "fulfilled": True,
            "ticket_id": ticket_id,
            "asset_id": asset_id,
            "shot_id": shot_id,
            "ticket": ticket,
        }
    )


@router.post("/manual-tickets/{ticket_id}/cancel")
async def api_v1_cancel_manual_ticket(request: Request, ticket_id: int) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    existing = query_one(
        paths.db_file, "SELECT id, status FROM manual_tickets WHERE id = ?", (ticket_id,)
    )
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Manual ticket #{ticket_id} not found")
    with get_conn(paths.db_file) as conn:
        cur = conn.execute(
            """
            UPDATE manual_tickets
            SET status = 'cancelled',
                closed_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
            WHERE id = ? AND status = 'open'
            """,
            (ticket_id,),
        )
        cancelled = bool(cur.rowcount)
    return JSONResponse({"cancelled": cancelled, "ticket_id": ticket_id})


__all__ = ["router"]

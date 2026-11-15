"""Routes that queue the describe and plan jobs of a footage (Phase 04)."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from videocreator.db import query_one
from videocreator.jobs import enqueue_job
from videocreator.paths import AppPaths
from videocreator.pipeline.plan_request import save_plan_request_params

router = APIRouter()


@router.post("/footage/{footage_id}/describe")
async def enqueue_describe_footage(request: Request, footage_id: int) -> RedirectResponse:
    paths: AppPaths = request.app.state.paths
    row = query_one(paths.db_file, "SELECT id FROM footage WHERE id = ?", (footage_id,))
    if row is None:
        raise HTTPException(status_code=404, detail="Footage not found")
    enqueue_job(paths.db_file, "describe", ref_id=footage_id)
    return RedirectResponse(url="/footage?msg=describe_queued", status_code=303)


@router.post("/footage/{footage_id}/plans")
async def enqueue_create_plans(
    request: Request,
    footage_id: int,
    count: int = Form(3),
    voice_lang: str = Form("vi"),
    caption_lang: str = Form("vi"),
    target_duration_s: float = Form(15.0),
) -> RedirectResponse:
    paths: AppPaths = request.app.state.paths
    row = query_one(paths.db_file, "SELECT id FROM footage WHERE id = ?", (footage_id,))
    if row is None:
        raise HTTPException(status_code=404, detail="Footage not found")

    v_lang: Literal["none", "vi", "en"] = (
        voice_lang if voice_lang in ("none", "vi", "en") else "vi"  # type: ignore[assignment]
    )
    c_lang: Literal["vi", "en"] = "en" if caption_lang == "en" else "vi"

    save_plan_request_params(
        paths,
        footage_id,
        count=count,
        voice_lang=v_lang,
        caption_lang=c_lang,
        target_duration_s=target_duration_s,
    )
    enqueue_job(paths.db_file, "plan", ref_id=footage_id)
    return RedirectResponse(url="/videos?msg=plan_queued", status_code=303)

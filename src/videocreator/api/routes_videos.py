"""Routes for AI shot description, remix plan generation, and video plan viewing/editing (Phase 04)."""
from __future__ import annotations
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from videocreator import __version__
from videocreator.api.view_models import enrich_video_row
from videocreator.config import load_settings
from videocreator.db import get_write_conn, query_all, query_one, record_audit
from videocreator.jobs import enqueue_job
from videocreator.jsonutil import loads_or
from videocreator.paths import AppPaths
from videocreator.pipeline.caption_limits import apply_caption_form
from videocreator.products import product_name_map
from videocreator.templating import get_templates

router = APIRouter()


@router.get("/videos", response_class=HTMLResponse)
async def videos_list_page(
    request: Request,
    msg: str | None = None,
) -> HTMLResponse:
    paths: AppPaths = request.app.state.paths
    cfg = load_settings(paths.config_file)
    templates = get_templates(paths)

    product_map = product_name_map(paths.db_file)

    raw_videos = query_all(paths.db_file, "SELECT * FROM videos ORDER BY id DESC")
    videos = [enrich_video_row(r, product_map) for r in raw_videos]

    return templates.TemplateResponse(
        request,
        "video_plan.html",
        {
            "page": "videos",
            "settings": cfg,
            "videos": videos,
            "editing_video": None,
            "shot_details": {},
            "msg": msg,
            "version": __version__,
        },
    )


@router.get("/videos/{video_id}", response_class=HTMLResponse)
async def video_detail_page(
    request: Request,
    video_id: int,
    msg: str | None = None,
) -> HTMLResponse:
    paths: AppPaths = request.app.state.paths
    cfg = load_settings(paths.config_file)
    templates = get_templates(paths)

    product_map = product_name_map(paths.db_file)

    row = query_one(paths.db_file, "SELECT * FROM videos WHERE id = ?", (video_id,))
    if row is None:
        raise HTTPException(status_code=404, detail="Video not found")

    editing_video = enrich_video_row(row, product_map)
    raw_videos = query_all(paths.db_file, "SELECT * FROM videos ORDER BY id DESC")
    videos = [enrich_video_row(r, product_map) for r in raw_videos]

    shot_details: dict[int, dict[str, Any]] = {}
    for s in query_all(paths.db_file, "SELECT * FROM shots"):
        shot_details[int(s["id"])] = s

    return templates.TemplateResponse(
        request,
        "video_plan.html",
        {
            "page": "videos",
            "settings": cfg,
            "videos": videos,
            "editing_video": editing_video,
            "shot_details": shot_details,
            "msg": msg,
            "version": __version__,
        },
    )


@router.post("/videos/{video_id}/update-plan")
async def update_video_plan(
    request: Request,
    video_id: int,
) -> RedirectResponse:
    paths: AppPaths = request.app.state.paths
    form = await request.form()

    with get_write_conn(paths.db_file) as conn:
        row = conn.execute("SELECT * FROM videos WHERE id = ?", (video_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Video not found")

        plan = loads_or(row["plan_json"], {})

        title = str(form.get("title") or plan.get("title") or "").strip()
        if title:
            plan["title"] = title

        shots = plan.get("shots") or []
        for idx, s in enumerate(shots):
            new_text = form.get(f"shot_text_{idx}")
            if new_text is not None:
                s["text"] = str(new_text).strip()

        base_caps = plan.get("captions") if isinstance(plan.get("captions"), dict) else {}
        override_caps = loads_or(row["captions_json"], {})
        if not isinstance(override_caps, dict):
            override_caps = {}
        captions = {k: (dict(v) if isinstance(v, dict) else v) for k, v in {**base_caps, **override_caps}.items()}
        apply_caption_form(form, captions)
        plan["captions"] = captions

        if form.get("clear_unverified") == "true":
            plan["unverified_claims"] = []

        conn.execute(
            """
            UPDATE videos
            SET plan_json = ?,
                captions_json = ?,
                unsupported_claims_json = ?
            WHERE id = ?
            """,
            (
                json.dumps(plan, ensure_ascii=False),
                json.dumps(plan.get("captions") or {}, ensure_ascii=False),
                json.dumps(plan.get("unverified_claims") or [], ensure_ascii=False),
                video_id,
            ),
        )
        record_audit(
            conn,
            actor="ui",
            action="video.plan_updated",
            object_type="video",
            object_id=video_id,
            detail=title,
        )

    return RedirectResponse(url=f"/videos/{video_id}?msg=plan_saved", status_code=303)


@router.post("/videos/{video_id}/render")
async def enqueue_render_video(request: Request, video_id: int) -> RedirectResponse:
    paths: AppPaths = request.app.state.paths
    row = query_one(paths.db_file, "SELECT id FROM videos WHERE id = ?", (video_id,))
    if row is None:
        raise HTTPException(status_code=404, detail="Video not found")
    enqueue_job(paths.db_file, "render", ref_id=video_id)
    return RedirectResponse(url=f"/videos/{video_id}?msg=render_queued", status_code=303)

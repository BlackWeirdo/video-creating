"""Routes for AI shot description, remix plan generation, and video plan viewing/editing (Phase 04)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from videocreator import __version__
from videocreator.api.routes_products import list_products
from videocreator.config import load_settings
from videocreator.db import get_conn, query_all, query_one, record_audit
from videocreator.jobs import enqueue_job
from videocreator.paths import AppPaths
from videocreator.pipeline.planner import (
    PLATFORM_CHAR_LIMITS,
    PLATFORM_HASHTAG_LIMITS,
    create_remix_plans,
)

router = APIRouter()


def save_plan_request_params(
    paths: AppPaths,
    footage_id: int,
    *,
    count: int = 3,
    voice_lang: Literal["none", "vi", "en"] = "vi",
    caption_lang: Literal["vi", "en"] = "vi",
    target_duration_s: float = 15.0,
    formula: dict[str, Any] | str | None = None,
    suggestion_id: int | None = None,
    auto_render: bool = False,
    preset_body: str | None = None,
) -> None:
    req_file = paths.work_dir / f"plan_req_{footage_id}.json"
    req_file.parent.mkdir(parents=True, exist_ok=True)
    req_file.write_text(
        json.dumps(
            {
                "count": max(1, min(6, int(count))),
                "voice_lang": voice_lang,
                "caption_lang": caption_lang,
                "target_duration_s": max(10.0, min(60.0, float(target_duration_s))),
                "formula": formula,
                "suggestion_id": suggestion_id,
                "auto_render": auto_render,
                "preset_body": preset_body,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def run_plan_footage(paths: AppPaths, footage_id: int) -> str:
    """Job handler for `plan`: reads saved request params and calls `create_remix_plans`."""
    req_file = paths.work_dir / f"plan_req_{footage_id}.json"
    params: dict[str, Any] = {
        "count": 3,
        "voice_lang": "vi",
        "caption_lang": "vi",
        "target_duration_s": 15.0,
        "formula": None,
        "suggestion_id": None,
        "auto_render": False,
        "preset_body": None,
    }
    if req_file.exists():
        try:
            params.update(json.loads(req_file.read_text(encoding="utf-8")))
        except Exception:
            pass
    target_ftg: int | None = footage_id if footage_id > 0 else None
    vids = create_remix_plans(
        paths,
        target_ftg,
        count=int(params["count"]),
        voice_lang=params["voice_lang"],
        caption_lang=params["caption_lang"],
        target_duration_s=float(params["target_duration_s"]),
        formula=params.get("formula"),
        suggestion_id=params.get("suggestion_id"),
        auto_render=bool(params.get("auto_render", False)),
        preset_body=params.get("preset_body"),
    )
    req_file.unlink(missing_ok=True)
    return f"Created {len(vids)} video plans: {vids}"


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


def _enrich_video_row(
    row: dict[str, Any],
    product_map: dict[int, str],
) -> dict[str, Any]:
    try:
        plan = json.loads(row.get("plan_json") or "{}")
    except Exception:
        plan = {}
    try:
        pids = [int(x) for x in json.loads(row.get("product_ids_json") or "[]")]
    except Exception:
        pids = []
    try:
        preflight = json.loads(row.get("preflight_json") or "{}")
    except Exception:
        preflight = {}
    unverified = plan.get("unverified_claims") or []
    return {
        **row,
        "plan": plan,
        "formula": plan.get("formula") or "hook-first",
        "mode": row.get("engine") or "ffmpeg",
        "title": plan.get("title") or f"Video #{row['id']}",
        "shots": plan.get("shots") or [],
        "captions": plan.get("captions") or {},
        "unverified_claims": unverified,
        "preflight": preflight,
        "product_ids": pids,
        "product_names": [product_map.get(pid, f"#{pid}") for pid in pids],
    }


@router.get("/videos", response_class=HTMLResponse)
async def videos_list_page(
    request: Request,
    msg: str | None = None,
) -> HTMLResponse:
    paths: AppPaths = request.app.state.paths
    cfg = load_settings(paths.config_file)
    templates = Jinja2Templates(directory=str(paths.templates_dir))

    all_products = list_products(paths.db_file, include_hidden=True)
    product_map = {p["id"]: p["name"] for p in all_products}

    raw_videos = query_all(paths.db_file, "SELECT * FROM videos ORDER BY id DESC")
    videos = [_enrich_video_row(r, product_map) for r in raw_videos]

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
    templates = Jinja2Templates(directory=str(paths.templates_dir))

    all_products = list_products(paths.db_file, include_hidden=True)
    product_map = {p["id"]: p["name"] for p in all_products}

    row = query_one(paths.db_file, "SELECT * FROM videos WHERE id = ?", (video_id,))
    if row is None:
        raise HTTPException(status_code=404, detail="Video not found")

    editing_video = _enrich_video_row(row, product_map)
    raw_videos = query_all(paths.db_file, "SELECT * FROM videos ORDER BY id DESC")
    videos = [_enrich_video_row(r, product_map) for r in raw_videos]

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
    row = query_one(paths.db_file, "SELECT * FROM videos WHERE id = ?", (video_id,))
    if row is None:
        raise HTTPException(status_code=404, detail="Video not found")

    form = await request.form()
    try:
        plan = json.loads(row.get("plan_json") or "{}")
    except Exception:
        plan = {}

    title = str(form.get("title") or plan.get("title") or "").strip()
    if title:
        plan["title"] = title

    shots = plan.get("shots") or []
    for idx, s in enumerate(shots):
        new_text = form.get(f"shot_text_{idx}")
        if new_text is not None:
            s["text"] = str(new_text).strip()

    captions = plan.get("captions") or {}
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
    plan["captions"] = captions

    if form.get("clear_unverified") == "true":
        plan["unverified_claims"] = []

    with get_conn(paths.db_file) as conn:
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

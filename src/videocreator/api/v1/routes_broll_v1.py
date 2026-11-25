"""Generative B-Roll creation, idea suggestion, and shot library endpoints for `/api/v1`."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from videocreator.ai.budget import get_daily_api_spend
from videocreator.ai.videogen_base import estimate_videogen_cost
from videocreator.api.v1.deps import resolve_workspace_id
from videocreator.config import load_settings
from videocreator.db import get_conn, query_all, query_one, record_audit
from videocreator.jobs import enqueue_job
from videocreator.paths import AppPaths
from videocreator.pipeline.broll import list_broll_shots
from videocreator.pipeline.broll_generate import BROLL_PRESET_PROMPTS, generate_broll
from videocreator.pipeline.broll_suggest import BROLL_SUGGEST_JOB_KIND, load_broll_ideas

router = APIRouter()

_ACTIVE_JOB_STATUSES = ("queued", "running", "waiting_quota")
_CANCELLABLE_JOB_STATUSES = ("queued", "waiting_quota")
SUGGEST_CANCELLED_ERROR = "Đã huỷ bởi người dùng"


class BrollCreateBody(BaseModel):
    prompt: str
    source: str = "manual"
    seconds: int = 6


@router.get("/broll")
async def api_v1_list_broll(
    request: Request,
    workspace_id: int | None = Query(default=None),
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    ws_id = resolve_workspace_id(paths.db_file, workspace_id)
    cfg = load_settings(paths.config_file)

    sources = [
        {
            "key": "manual",
            "label": "Trạm việc tay (Muse / Gemini / Flow — $0 gói thuê bao, mặc định)",
            "est_6s": 0.0,
        }
    ]
    for m_key, m_cfg in cfg.videogen.models.items():
        sources.append(
            {
                "key": m_key,
                "label": f"API: {m_key.upper()} (${m_cfg.per_second_usd:.2f}/giây)",
                "est_6s": estimate_videogen_cost(cfg, m_key, 6),
            }
        )

    suggest_job = query_one(
        paths.db_file,
        "SELECT id, status, error, created_at FROM jobs WHERE kind = ? ORDER BY id DESC LIMIT 1",
        (BROLL_SUGGEST_JOB_KIND,),
    )
    open_tickets = query_all(
        paths.db_file,
        "SELECT * FROM manual_tickets WHERE status = 'open' ORDER BY id DESC",
    )

    return JSONResponse(
        {
            "workspace_id": ws_id,
            "presets": BROLL_PRESET_PROMPTS,
            "ideas_batch": load_broll_ideas(paths.db_file),
            "suggest_job": suggest_job,
            "suggest_active": bool(suggest_job and suggest_job["status"] in _ACTIVE_JOB_STATUSES),
            "suggest_cancellable": bool(
                suggest_job and suggest_job["status"] in _CANCELLABLE_JOB_STATUSES
            ),
            "sources": sources,
            "broll_shots": list_broll_shots(paths.db_file),
            "open_tickets": open_tickets,
            "gen_spent_usd": get_daily_api_spend(paths.db_file, bucket="generative"),
            "gen_limit_usd": cfg.budget.generative_daily_usd,
        }
    )


@router.post("/broll/suggest")
async def api_v1_suggest_broll(request: Request) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    placeholders = ",".join("?" for _ in _ACTIVE_JOB_STATUSES)
    pending = query_one(
        paths.db_file,
        f"SELECT id FROM jobs WHERE kind = ? AND status IN ({placeholders}) LIMIT 1",
        (BROLL_SUGGEST_JOB_KIND, *_ACTIVE_JOB_STATUSES),
    )
    if pending is not None:
        return JSONResponse({"queued": False, "job_id": int(pending["id"])})
    job_id = enqueue_job(paths.db_file, BROLL_SUGGEST_JOB_KIND)
    return JSONResponse({"queued": True, "job_id": job_id}, status_code=201)


@router.post("/broll/suggest/cancel")
async def api_v1_cancel_broll_suggest(request: Request) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    placeholders = ",".join("?" for _ in _CANCELLABLE_JOB_STATUSES)
    with get_conn(paths.db_file) as conn:
        cur = conn.execute(
            f"""
            UPDATE jobs
            SET status = 'failed', error = ?,
                finished_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
            WHERE kind = ? AND status IN ({placeholders})
            """,
            (SUGGEST_CANCELLED_ERROR, BROLL_SUGGEST_JOB_KIND, *_CANCELLABLE_JOB_STATUSES),
        )
        cancelled = int(cur.rowcount or 0)
        if cancelled:
            record_audit(
                conn,
                actor="api",
                action="broll.suggest_cancelled",
                object_type="job",
                detail=f"cancelled={cancelled}",
            )
    return JSONResponse({"cancelled": cancelled})


@router.post("/broll", status_code=201)
async def api_v1_create_broll(request: Request, body: BrollCreateBody) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    try:
        res = await asyncio.to_thread(
            generate_broll,
            paths,
            prompt=body.prompt.strip(),
            source=body.source.strip(),
            seconds=max(4, min(10, int(body.seconds))),
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(res, status_code=201)


@router.delete("/broll/{shot_id}")
async def api_v1_delete_broll_shot(request: Request, shot_id: int) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    with get_conn(paths.db_file) as conn:
        row = conn.execute(
            "SELECT asset_id FROM shots WHERE id = ? AND footage_id IS NULL",
            (shot_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"B-roll shot #{shot_id} not found")
        aid = row["asset_id"]
        conn.execute("DELETE FROM shots WHERE id = ?", (shot_id,))
        if aid:
            conn.execute("DELETE FROM assets WHERE id = ?", (aid,))
    return JSONResponse({"deleted": True, "shot_id": shot_id})


__all__ = ["router"]

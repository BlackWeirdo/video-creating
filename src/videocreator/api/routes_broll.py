"""Routes for Generative B-Roll creation (`manual`, `kling`, `seedance`, `veo`) and library management (Phase 14)."""
from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from videocreator import __version__
from videocreator.ai.budget import get_daily_api_spend
from videocreator.ai.videogen_base import estimate_videogen_cost
from videocreator.config import load_settings
from videocreator.db import get_conn, query_all, query_one, record_audit
from videocreator.jobs import enqueue_job
from videocreator.paths import AppPaths
from videocreator.pipeline.broll import (
    BROLL_PRESET_PROMPTS,
    generate_broll,
    list_broll_shots,
)
from videocreator.pipeline.broll_suggest import BROLL_SUGGEST_JOB_KIND, load_broll_ideas

router = APIRouter()

_ACTIVE_JOB_STATUSES = ("queued", "running", "waiting_quota")
# Only jobs not yet running can be cancelled: a running job's thread cannot be stopped and would
# overwrite the cancel when it finishes.
_CANCELLABLE_JOB_STATUSES = ("queued", "waiting_quota")
SUGGEST_CANCELLED_ERROR = "Đã huỷ bởi người dùng"


@router.get("/broll", response_class=HTMLResponse)
async def broll_page(
    request: Request,
    msg: str | None = None,
    err: str | None = None,
) -> HTMLResponse:
    paths: AppPaths = request.app.state.paths
    cfg = load_settings(paths.config_file)
    templates = Jinja2Templates(directory=str(paths.templates_dir))

    broll_shots = list_broll_shots(paths.db_file)
    open_tickets = query_all(
        paths.db_file,
        "SELECT * FROM manual_tickets WHERE status = 'open' ORDER BY id DESC",
    )
    gen_spent = get_daily_api_spend(paths.db_file, bucket="generative")

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

    return templates.TemplateResponse(
        request,
        "broll.html",
        {
            "page": "broll",
            "settings": cfg,
            "presets": BROLL_PRESET_PROMPTS,
            "ideas_batch": load_broll_ideas(paths.db_file),
            "suggest_job": suggest_job,
            "suggest_active": bool(suggest_job and suggest_job["status"] in _ACTIVE_JOB_STATUSES),
            "suggest_cancellable": bool(
                suggest_job and suggest_job["status"] in _CANCELLABLE_JOB_STATUSES
            ),
            "suggest_cancelled_error": SUGGEST_CANCELLED_ERROR,
            "sources": sources,
            "broll_shots": broll_shots,
            "open_tickets": open_tickets,
            "gen_spent": gen_spent,
            "msg": msg,
            "err": err,
            "version": __version__,
        },
    )


@router.post("/broll/suggest")
async def suggest_broll_route(request: Request) -> RedirectResponse:
    """Queues one `broll_suggest` job; a second click while one is pending does nothing."""
    paths: AppPaths = request.app.state.paths
    placeholders = ",".join("?" for _ in _ACTIVE_JOB_STATUSES)
    pending = query_one(
        paths.db_file,
        f"SELECT id FROM jobs WHERE kind = ? AND status IN ({placeholders}) LIMIT 1",
        (BROLL_SUGGEST_JOB_KIND, *_ACTIVE_JOB_STATUSES),
    )
    if pending is None:
        enqueue_job(paths.db_file, BROLL_SUGGEST_JOB_KIND)
    return RedirectResponse(url="/broll?msg=suggest_queued", status_code=303)


@router.post("/broll/suggest/cancel")
async def cancel_broll_suggest_route(request: Request) -> RedirectResponse:
    """Cancels a `broll_suggest` job that is queued or waiting for AI quota."""
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
                actor="ui",
                action="broll.suggest_cancelled",
                object_type="job",
                detail=f"cancelled={cancelled}",
            )
    msg = "suggest_cancelled" if cancelled else "suggest_not_cancellable"
    return RedirectResponse(url=f"/broll?msg={msg}", status_code=303)


@router.post("/broll/create")
async def create_broll_route(
    request: Request,
    prompt: str = Form(...),
    source: str = Form("manual"),
    seconds: int = Form(6),
) -> RedirectResponse:
    paths: AppPaths = request.app.state.paths
    try:
        res = generate_broll(
            paths,
            prompt=prompt.strip(),
            source=source.strip(),
            seconds=max(4, min(10, int(seconds))),
        )
        if res.get("mode") == "manual":
            return RedirectResponse(
                url=f"/broll?msg=ticket_{res['ticket_id']}", status_code=303
            )
        return RedirectResponse(
            url=f"/broll?msg=shot_{res.get('shot_id')}", status_code=303
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/broll/{shot_id}/delete")
async def delete_broll_shot_route(
    request: Request,
    shot_id: int,
) -> RedirectResponse:
    paths: AppPaths = request.app.state.paths
    with get_conn(paths.db_file) as conn:
        row = conn.execute(
            "SELECT asset_id FROM shots WHERE id = ? AND footage_id IS NULL",
            (shot_id,),
        ).fetchone()
        if row:
            aid = row["asset_id"]
            conn.execute("DELETE FROM shots WHERE id = ?", (shot_id,))
            if aid:
                conn.execute("DELETE FROM assets WHERE id = ?", (aid,))
    return RedirectResponse(url="/broll?msg=deleted", status_code=303)

"""Account connection, post scheduling, publishing history, and manual bundle download routes (Phase 07)."""
from __future__ import annotations

import hashlib
from typing import Any, Literal

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from videocreator import __version__
from videocreator.config import load_settings
from videocreator.db import get_conn, query_all, query_one, record_audit
from videocreator.paths import AppPaths
from videocreator.posting.meta_auth import list_pages_and_instagram
from videocreator.posting.service import (
    build_manual_bundle_zip,
    cancel_scheduled_post,
    confirm_user_action_post,
    is_posting_paused,
    publish_due_posts,
    reschedule_post,
    retry_failed_post,
    schedule_approved_video,
    set_posting_paused,
    utc_now_iso,
)
from videocreator.secrets_store import SecretsStore

router = APIRouter()


def upsert_account(
    paths: AppPaths,
    *,
    platform: Literal["facebook", "instagram", "threads", "tiktok"],
    external_id: str,
    name: str,
    access_token: str,
    lang: Literal["vi", "en"] = "vi",
    token_expires_at: str | None = None,
    secrets_store: SecretsStore | None = None,
) -> int:
    clean_ext = external_id.strip()
    clean_name = name.strip() or f"{platform}:{clean_ext}"
    if not clean_ext:
        raise ValueError("Account external_id is required")

    sec = secrets_store or SecretsStore(paths.secrets_file)
    secret_key = f"ACCOUNT_TOKEN_{platform.upper()}_{hashlib.md5(clean_ext.encode('utf-8')).hexdigest()[:10]}"
    if access_token.strip():
        sec.set(secret_key, access_token.strip())

    with get_conn(paths.db_file) as conn:
        conn.execute(
            """
            INSERT INTO accounts (
                platform, external_id, name, lang, secret_key, token_expires_at, enabled
            )
            VALUES (?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(platform, external_id) DO UPDATE SET
                name = excluded.name,
                lang = excluded.lang,
                secret_key = excluded.secret_key,
                token_expires_at = COALESCE(excluded.token_expires_at, accounts.token_expires_at),
                enabled = 1
            """,
            (platform, clean_ext, clean_name, lang, secret_key, token_expires_at),
        )
        row = conn.execute(
            "SELECT id FROM accounts WHERE platform = ? AND external_id = ?",
            (platform, clean_ext),
        ).fetchone()
        acc_id = int(row["id"]) if row else 0
        record_audit(
            conn,
            actor="ui",
            action="account.upserted",
            object_type="account",
            object_id=acc_id,
            detail=f"{platform}:{clean_name} ({clean_ext})",
        )
        return acc_id


@router.get("/accounts", response_class=HTMLResponse)
async def accounts_page(
    request: Request,
    msg: str | None = None,
    err: str | None = None,
) -> HTMLResponse:
    paths: AppPaths = request.app.state.paths
    cfg = load_settings(paths.config_file)
    templates = Jinja2Templates(directory=str(paths.templates_dir))
    secrets: SecretsStore = request.app.state.secrets

    rows = query_all(paths.db_file, "SELECT * FROM accounts ORDER BY platform, id ASC")
    accounts: list[dict[str, Any]] = []
    for r in rows:
        accounts.append(
            {
                **r,
                "has_token": secrets.has(str(r["secret_key"])),
            }
        )

    return templates.TemplateResponse(
        request,
        "accounts.html",
        {
            "page": "accounts",
            "settings": cfg,
            "accounts": accounts,
            "msg": msg,
            "err": err,
            "version": __version__,
        },
    )


@router.post("/accounts/connect-meta")
async def connect_meta_token(
    request: Request,
    token: str = Form(...),
    default_lang: str = Form("vi"),
) -> RedirectResponse:
    paths: AppPaths = request.app.state.paths
    secrets: SecretsStore = request.app.state.secrets
    lang: Literal["vi", "en"] = "en" if default_lang == "en" else "vi"
    try:
        discovered = list_pages_and_instagram(token)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Lỗi kết nối Meta Graph API: {exc}") from exc

    for item in discovered:
        upsert_account(
            paths,
            platform=item["platform"],
            external_id=item["external_id"],
            name=item["name"],
            access_token=item["access_token"],
            lang=lang,
            secrets_store=secrets,
        )
    return RedirectResponse(url=f"/accounts?msg=connected_{len(discovered)}", status_code=303)


@router.post("/accounts/add")
async def add_account_manually(
    request: Request,
    platform: str = Form("facebook"),
    external_id: str = Form(...),
    name: str = Form(...),
    lang: str = Form("vi"),
    access_token: str = Form(...),
) -> RedirectResponse:
    paths: AppPaths = request.app.state.paths
    secrets: SecretsStore = request.app.state.secrets
    plat: Literal["facebook", "instagram", "threads", "tiktok"] = (
        platform if platform in ("facebook", "instagram", "threads", "tiktok") else "facebook"  # type: ignore[assignment]
    )
    clean_lang: Literal["vi", "en"] = "en" if lang == "en" else "vi"
    upsert_account(
        paths,
        platform=plat,
        external_id=external_id,
        name=name,
        access_token=access_token,
        lang=clean_lang,
        secrets_store=secrets,
    )
    return RedirectResponse(url="/accounts?msg=saved", status_code=303)


@router.post("/accounts/{account_id}/toggle")
async def toggle_account(request: Request, account_id: int) -> RedirectResponse:
    paths: AppPaths = request.app.state.paths
    with get_conn(paths.db_file) as conn:
        conn.execute(
            "UPDATE accounts SET enabled = CASE WHEN enabled = 1 THEN 0 ELSE 1 END WHERE id = ?",
            (account_id,),
        )
    return RedirectResponse(url="/accounts?msg=toggled", status_code=303)


@router.post("/accounts/{account_id}/delete")
async def delete_account(request: Request, account_id: int) -> RedirectResponse:
    paths: AppPaths = request.app.state.paths
    secrets: SecretsStore = request.app.state.secrets
    row = query_one(paths.db_file, "SELECT secret_key FROM accounts WHERE id = ?", (account_id,))
    if row:
        secrets.delete(str(row["secret_key"]))
    with get_conn(paths.db_file) as conn:
        conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
    return RedirectResponse(url="/accounts?msg=deleted", status_code=303)


@router.post("/accounts/{account_id}/slots")
async def update_account_slots(
    request: Request,
    account_id: int,
    slots: str = Form(""),
) -> RedirectResponse:
    import json

    paths: AppPaths = request.app.state.paths
    parts = [s.strip() for s in slots.replace(",", " ").split() if s.strip() and ":" in s]
    slots_val = json.dumps(parts) if parts else None
    with get_conn(paths.db_file) as conn:
        conn.execute(
            "UPDATE accounts SET slots_json = ? WHERE id = ?",
            (slots_val, account_id),
        )
    return RedirectResponse(url="/accounts?msg=slots_saved", status_code=303)


@router.get("/schedule", response_class=HTMLResponse)
async def schedule_page(
    request: Request,
    msg: str | None = None,
) -> HTMLResponse:
    paths: AppPaths = request.app.state.paths
    cfg = load_settings(paths.config_file)
    templates = Jinja2Templates(directory=str(paths.templates_dir))

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
        publish_due_posts(paths)
        return RedirectResponse(url="/schedule?msg=posted_now", status_code=303)

    return RedirectResponse(url="/schedule?msg=scheduled", status_code=303)


@router.get("/videos/{video_id}/manual-bundle")
async def download_manual_bundle(request: Request, video_id: int) -> FileResponse:
    paths: AppPaths = request.app.state.paths
    try:
        zip_path = build_manual_bundle_zip(paths, video_id)
    except (LookupError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=f"video_{video_id}_manual_bundle.zip",
    )


@router.get("/performance", response_class=HTMLResponse)
async def performance_page(
    request: Request,
    msg: str | None = None,
) -> HTMLResponse:
    from videocreator.posting.metrics import list_performance_rows
    from videocreator.reports import weekly_summary

    paths: AppPaths = request.app.state.paths
    cfg = load_settings(paths.config_file)
    templates = Jinja2Templates(directory=str(paths.templates_dir))
    rows = list_performance_rows(paths.db_file)
    summary_text = weekly_summary(paths)

    return templates.TemplateResponse(
        request,
        "performance.html",
        {
            "page": "performance",
            "settings": cfg,
            "rows": rows,
            "weekly_summary_text": summary_text,
            "msg": msg,
            "version": __version__,
        },
    )


@router.post("/performance/collect")
async def collect_metrics_now_route(request: Request) -> RedirectResponse:
    from videocreator.posting.metrics import collect_due_metrics

    paths: AppPaths = request.app.state.paths
    count = collect_due_metrics(paths)
    return RedirectResponse(url=f"/performance?msg=collected_{count}", status_code=303)


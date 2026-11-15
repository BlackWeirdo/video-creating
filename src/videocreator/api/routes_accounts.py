"""Account connection routes: Meta token, manual add, enable/disable, per-account slots (Phase 07)."""
from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from videocreator import __version__
from videocreator.config import load_settings
from videocreator.db import get_conn, query_all, query_one
from videocreator.paths import AppPaths
from videocreator.posting.accounts import upsert_account
from videocreator.posting.meta_auth import list_pages_and_instagram
from videocreator.secrets_store import SecretsStore
from videocreator.templating import get_templates

router = APIRouter()


@router.get("/accounts", response_class=HTMLResponse)
async def accounts_page(
    request: Request,
    msg: str | None = None,
    err: str | None = None,
) -> HTMLResponse:
    paths: AppPaths = request.app.state.paths
    cfg = load_settings(paths.config_file)
    templates = get_templates(paths)
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
        discovered = await asyncio.to_thread(list_pages_and_instagram, token)
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

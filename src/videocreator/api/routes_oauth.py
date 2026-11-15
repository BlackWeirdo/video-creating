"""OAuth 2.0 routes for Threads and TikTok (`GET /oauth/{platform}/start`, `/callback`, `POST /code`, Phase 11)."""
from __future__ import annotations

import asyncio
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from videocreator.paths import AppPaths
from videocreator.posting.oauth import build_authorize_url
from videocreator.posting.oauth_exchange import exchange_code_for_account
from videocreator.secrets_store import SecretsStore

router = APIRouter()


def _validate_oauth_platform(platform: str) -> Literal["threads", "tiktok"]:
    if platform not in ("threads", "tiktok"):
        raise HTTPException(
            status_code=400,
            detail=f"Nền tảng OAuth không hỗ trợ: {platform} (chỉ hỗ trợ threads, tiktok)",
        )
    return platform  # type: ignore[return-value]


@router.get("/oauth/{platform}/start")
async def oauth_start_route(
    request: Request,
    platform: str,
    lang: str = "vi",
    redirect_uri: str | None = None,
) -> RedirectResponse:
    plat = _validate_oauth_platform(platform)
    paths: AppPaths = request.app.state.paths
    secrets: SecretsStore = request.app.state.secrets
    clean_lang: Literal["vi", "en"] = "en" if lang == "en" else "vi"
    default_cb = str(request.base_url).rstrip("/") + f"/oauth/{plat}/callback"
    cb_uri = (redirect_uri or default_cb).strip()

    try:
        auth_url, _ = build_authorize_url(
            paths,
            plat,
            redirect_uri=cb_uri,
            lang=clean_lang,
            secrets_store=secrets,
        )
    except ValueError as exc:
        return RedirectResponse(
            url=f"/accounts?err={quote(str(exc))}", status_code=303
        )

    return RedirectResponse(url=auth_url, status_code=302)


@router.get("/oauth/{platform}/callback")
async def oauth_callback_route(
    request: Request,
    platform: str,
    code: str = "",
    state: str = "",
    error: str = "",
) -> RedirectResponse:
    plat = _validate_oauth_platform(platform)
    if error:
        return RedirectResponse(
            url=f"/accounts?err={quote(f'OAuth {plat} từ chối: {error}')}",
            status_code=303,
        )
    paths: AppPaths = request.app.state.paths
    secrets: SecretsStore = request.app.state.secrets
    try:
        await asyncio.to_thread(
            exchange_code_for_account,
            paths,
            plat,
            code=code,
            state=state,
            secrets_store=secrets,
        )
    except Exception as exc:
        return RedirectResponse(
            url=f"/accounts?err={quote(str(exc))}",
            status_code=303,
        )
    return RedirectResponse(url=f"/accounts?msg=oauth_{plat}", status_code=303)


@router.post("/oauth/{platform}/code")
async def oauth_paste_code_route(
    request: Request,
    platform: str,
    code: str = Form(...),
    state: str = Form(...),
) -> RedirectResponse:
    plat = _validate_oauth_platform(platform)
    paths: AppPaths = request.app.state.paths
    secrets: SecretsStore = request.app.state.secrets
    try:
        await asyncio.to_thread(
            exchange_code_for_account,
            paths,
            plat,
            code=code,
            state=state,
            secrets_store=secrets,
        )
    except Exception as exc:
        return RedirectResponse(
            url=f"/accounts?err={quote(str(exc))}",
            status_code=303,
        )
    return RedirectResponse(url=f"/accounts?msg=oauth_{plat}", status_code=303)

"""OAuth 2.0 routes for Threads and TikTok (`GET /oauth/{platform}/start`, `/callback`, `POST /code`, Phase 11)."""
from __future__ import annotations

import asyncio
from typing import Literal
from urllib.parse import quote, urlparse

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from videocreator.logging_setup import redact_text
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


def _safe_err(exc: Exception, secrets: SecretsStore) -> str:
    vals = sorted((v for v in secrets.all().values() if len(v) >= 6), key=len, reverse=True)
    return quote(redact_text(str(exc), vals)[:240])


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
    expected_path = f"/oauth/{plat}/callback"
    default_cb = str(request.base_url).rstrip("/") + expected_path
    cb_uri = (redirect_uri or default_cb).strip()
    if redirect_uri:
        parsed_cb = urlparse(cb_uri)
        parsed_base = urlparse(default_cb)
        if (
            parsed_cb.scheme not in ("http", "https")
            or parsed_cb.netloc.lower() != parsed_base.netloc.lower()
            or parsed_cb.path != expected_path
        ):
            raise HTTPException(status_code=400, detail="redirect_uri không hợp lệ (phải cùng host ứng dụng)")

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
            url=f"/accounts?err={_safe_err(exc, secrets)}", status_code=303
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
            url=f"/accounts?err={quote(f'OAuth {plat} từ chối: {error[:160]}')}",
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
            url=f"/accounts?err={_safe_err(exc, secrets)}",
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
            url=f"/accounts?err={_safe_err(exc, secrets)}",
            status_code=303,
        )
    return RedirectResponse(url=f"/accounts?msg=oauth_{plat}", status_code=303)

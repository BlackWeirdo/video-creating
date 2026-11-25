"""Local-only Muse Gateway administration endpoints (`/api/v1/muse/admin/*`)."""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from videocreator.api.v1.routes_muse_v1 import map_muse_http_error
from videocreator.muse_gateway.admin import (
    cancel_muse_login_capture,
    check_muse_gateway_update,
    cleanup_muse_gateway_tasks,
    create_muse_combo,
    delete_muse_account,
    delete_muse_combo,
    get_muse_gateway_overview,
    get_muse_gateway_settings,
    get_muse_gateway_usage,
    get_muse_gateway_usage_csv,
    get_muse_pool,
    import_muse_account_cookies,
    keepalive_muse_pool,
    list_muse_accounts,
    list_muse_combos,
    list_muse_gateway_keys,
    open_muse_account_browser,
    patch_muse_account,
    patch_muse_combo,
    patch_muse_gateway_key,
    patch_muse_gateway_settings,
    patch_muse_pool,
    poll_muse_login_capture,
    start_muse_login_capture,
    test_muse_account,
)
from videocreator.paths import AppPaths

router = APIRouter()


class MuseLoginStartBody(BaseModel):
    browser_type: str = "chrome"
    target_session_id: str | None = None


class MuseCookieImportBody(BaseModel):
    name: str = "Muse Account"
    cookies: str


class MuseAccountPatchBody(BaseModel):
    name: str | None = None
    proxy: str | None = None
    enabled: bool | None = None
    reset_cooldown: bool = False
    close_lane: int | None = None


class MuseOpenBrowserBody(BaseModel):
    url: str | None = None
    browser_type: str = "chrome"


class MusePoolPatchBody(BaseModel):
    strategy: str


class MuseComboCreateBody(BaseModel):
    name: str
    account_ids: list[str] = Field(default_factory=list)
    strategy: str = "round-robin"
    kind: str | None = None


class MuseComboPatchBody(BaseModel):
    name: str | None = None
    account_ids: list[str] | None = None
    strategy: str | None = None
    kind: str | None = None


class MuseKeyPatchBody(BaseModel):
    enabled: bool | None = None
    access: dict[str, Any] | None = None
    require_auth: bool | None = None


class MuseCleanupBody(BaseModel):
    scope: str = "failed"


@router.get("/muse/admin/accounts")
async def api_v1_muse_admin_accounts(request: Request) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    try:
        accounts = await asyncio.to_thread(list_muse_accounts, paths)
        return JSONResponse({"accounts": accounts})
    except Exception as exc:
        raise map_muse_http_error(exc) from exc


@router.post("/muse/admin/accounts/cookies", status_code=201)
async def api_v1_muse_admin_import_cookies(
    request: Request, body: MuseCookieImportBody
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    try:
        res = await asyncio.to_thread(
            import_muse_account_cookies, paths, name=body.name, cookies=body.cookies
        )
        return JSONResponse(res, status_code=201)
    except Exception as exc:
        raise map_muse_http_error(exc) from exc


@router.post("/muse/admin/accounts/login")
async def api_v1_muse_admin_login_start(
    request: Request, body: MuseLoginStartBody | None = None
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    payload = body or MuseLoginStartBody()
    try:
        res = await asyncio.to_thread(
            start_muse_login_capture,
            paths,
            browser_type=payload.browser_type,
            target_session_id=payload.target_session_id,
        )
        return JSONResponse(res)
    except Exception as exc:
        raise map_muse_http_error(exc) from exc


@router.get("/muse/admin/accounts/login/{job_id}")
async def api_v1_muse_admin_login_poll(request: Request, job_id: str) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    try:
        return JSONResponse(await asyncio.to_thread(poll_muse_login_capture, paths, job_id))
    except Exception as exc:
        raise map_muse_http_error(exc) from exc


@router.delete("/muse/admin/accounts/login/{job_id}")
async def api_v1_muse_admin_login_cancel(request: Request, job_id: str) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    try:
        return JSONResponse(await asyncio.to_thread(cancel_muse_login_capture, paths, job_id))
    except Exception as exc:
        raise map_muse_http_error(exc) from exc


@router.patch("/muse/admin/accounts/{account_id}")
async def api_v1_muse_admin_patch_account(
    request: Request, account_id: str, body: MuseAccountPatchBody
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    try:
        acc = await asyncio.to_thread(
            patch_muse_account,
            paths,
            account_id,
            name=body.name,
            proxy=body.proxy,
            enabled=body.enabled,
            reset_cooldown=body.reset_cooldown,
            close_lane=body.close_lane,
        )
        return JSONResponse({"account": acc})
    except Exception as exc:
        raise map_muse_http_error(exc) from exc


@router.delete("/muse/admin/accounts/{account_id}")
async def api_v1_muse_admin_delete_account(request: Request, account_id: str) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    try:
        await asyncio.to_thread(delete_muse_account, paths, account_id)
        return JSONResponse({"deleted": True})
    except Exception as exc:
        raise map_muse_http_error(exc) from exc


@router.post("/muse/admin/accounts/{account_id}/test")
async def api_v1_muse_admin_test_account(request: Request, account_id: str) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    try:
        return JSONResponse(await asyncio.to_thread(test_muse_account, paths, account_id))
    except Exception as exc:
        raise map_muse_http_error(exc) from exc


@router.post("/muse/admin/accounts/{account_id}/open-browser")
async def api_v1_muse_admin_open_browser(
    request: Request, account_id: str, body: MuseOpenBrowserBody | None = None
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    payload = body or MuseOpenBrowserBody()
    try:
        res = await asyncio.to_thread(
            open_muse_account_browser,
            paths,
            account_id,
            url=payload.url,
            browser_type=payload.browser_type,
        )
        return JSONResponse(res)
    except Exception as exc:
        raise map_muse_http_error(exc) from exc


@router.get("/muse/admin/pool")
async def api_v1_muse_admin_get_pool(request: Request) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    try:
        return JSONResponse(await asyncio.to_thread(get_muse_pool, paths))
    except Exception as exc:
        raise map_muse_http_error(exc) from exc


@router.patch("/muse/admin/pool")
async def api_v1_muse_admin_patch_pool(request: Request, body: MusePoolPatchBody) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    try:
        return JSONResponse(await asyncio.to_thread(patch_muse_pool, paths, strategy=body.strategy))
    except Exception as exc:
        raise map_muse_http_error(exc) from exc


@router.post("/muse/admin/pool/keepalive")
async def api_v1_muse_admin_keepalive_pool(request: Request) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    try:
        return JSONResponse(await asyncio.to_thread(keepalive_muse_pool, paths))
    except Exception as exc:
        raise map_muse_http_error(exc) from exc


@router.get("/muse/admin/combos")
async def api_v1_muse_admin_list_combos(request: Request) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    try:
        return JSONResponse({"combos": await asyncio.to_thread(list_muse_combos, paths)})
    except Exception as exc:
        raise map_muse_http_error(exc) from exc


@router.post("/muse/admin/combos", status_code=201)
async def api_v1_muse_admin_create_combo(
    request: Request, body: MuseComboCreateBody
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    try:
        combo = await asyncio.to_thread(
            create_muse_combo,
            paths,
            name=body.name,
            account_ids=body.account_ids,
            strategy=body.strategy,
            kind=body.kind,
        )
        return JSONResponse({"combo": combo}, status_code=201)
    except Exception as exc:
        raise map_muse_http_error(exc) from exc


@router.patch("/muse/admin/combos/{combo_id}")
async def api_v1_muse_admin_patch_combo(
    request: Request, combo_id: str, body: MuseComboPatchBody
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    patch_dict = {k: v for k, v in body.model_dump().items() if v is not None}
    try:
        combos = await asyncio.to_thread(patch_muse_combo, paths, combo_id, patch_dict)
        return JSONResponse({"combos": combos})
    except Exception as exc:
        raise map_muse_http_error(exc) from exc


@router.delete("/muse/admin/combos/{combo_id}")
async def api_v1_muse_admin_delete_combo(request: Request, combo_id: str) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    try:
        combos = await asyncio.to_thread(delete_muse_combo, paths, combo_id)
        return JSONResponse({"combos": combos})
    except Exception as exc:
        raise map_muse_http_error(exc) from exc


@router.get("/muse/admin/settings")
async def api_v1_muse_admin_get_settings(request: Request) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    try:
        return JSONResponse({"settings": await asyncio.to_thread(get_muse_gateway_settings, paths)})
    except Exception as exc:
        raise map_muse_http_error(exc) from exc


@router.patch("/muse/admin/settings")
async def api_v1_muse_admin_patch_settings(request: Request) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    raw_body = await request.json()
    if not isinstance(raw_body, dict):
        return JSONResponse({"error": "JSON object expected"}, status_code=400)
    try:
        updated = await asyncio.to_thread(patch_muse_gateway_settings, paths, raw_body)
        return JSONResponse({"settings": updated})
    except Exception as exc:
        raise map_muse_http_error(exc) from exc


@router.get("/muse/admin/keys")
async def api_v1_muse_admin_list_keys(request: Request) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    try:
        return JSONResponse(await asyncio.to_thread(list_muse_gateway_keys, paths))
    except Exception as exc:
        raise map_muse_http_error(exc) from exc


@router.patch("/muse/admin/keys/{key_id}")
async def api_v1_muse_admin_patch_key(
    request: Request, key_id: str, body: MuseKeyPatchBody
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    try:
        res = await asyncio.to_thread(
            patch_muse_gateway_key,
            paths,
            key_id,
            enabled=body.enabled,
            access=body.access,
            require_auth=body.require_auth,
        )
        return JSONResponse(res)
    except Exception as exc:
        raise map_muse_http_error(exc) from exc


@router.get("/muse/admin/usage")
async def api_v1_muse_admin_usage(
    request: Request, range: str = Query(default="today")
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    try:
        return JSONResponse(await asyncio.to_thread(get_muse_gateway_usage, paths, range))
    except Exception as exc:
        raise map_muse_http_error(exc) from exc


@router.get("/muse/admin/usage.csv")
async def api_v1_muse_admin_usage_csv(
    request: Request, range: str = Query(default="today")
) -> PlainTextResponse:
    paths: AppPaths = request.app.state.paths
    try:
        csv_txt = await asyncio.to_thread(get_muse_gateway_usage_csv, paths, range)
        return PlainTextResponse(
            csv_txt,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="muse-usage-{range}.csv"'},
        )
    except Exception as exc:
        raise map_muse_http_error(exc) from exc


@router.get("/muse/admin/overview")
async def api_v1_muse_admin_overview(request: Request) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    try:
        return JSONResponse(await asyncio.to_thread(get_muse_gateway_overview, paths))
    except Exception as exc:
        raise map_muse_http_error(exc) from exc


@router.post("/muse/admin/cleanup")
async def api_v1_muse_admin_cleanup(
    request: Request, body: MuseCleanupBody | None = None
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    payload = body or MuseCleanupBody()
    try:
        return JSONResponse(await asyncio.to_thread(cleanup_muse_gateway_tasks, paths, payload.scope))
    except Exception as exc:
        raise map_muse_http_error(exc) from exc


@router.get("/muse/admin/update-check")
async def api_v1_muse_admin_update_check(request: Request) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    try:
        return JSONResponse(await asyncio.to_thread(check_muse_gateway_update, paths))
    except Exception as exc:
        raise map_muse_http_error(exc) from exc

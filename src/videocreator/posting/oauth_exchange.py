"""OAuth code exchange for Threads and TikTok: tokens in, connected `accounts` row out (Phase 11)."""
from __future__ import annotations
from datetime import datetime, timedelta
from typing import Any, Literal

import httpx

from videocreator.db import query_one
from videocreator.paths import AppPaths
from videocreator.posting.oauth import (
    THREADS_LONG_LIVED_URL,
    THREADS_ME_URL,
    THREADS_TOKEN_URL,
    TIKTOK_TOKEN_URL,
    TIKTOK_USER_INFO_URL,
    YOUTUBE_CHANNELS_URL,
    YOUTUBE_TOKEN_URL,
    consume_oauth_state,
)
from videocreator.secrets_store import SecretsStore
from videocreator.timeutil import UTC_ISO_FORMAT, utc_now


def _expiry_iso(base_utc: datetime, expires_in_s: int) -> str:
    return (base_utc + timedelta(seconds=expires_in_s)).strftime(UTC_ISO_FORMAT)


def _exchange_threads(
    paths: AppPaths,
    client: Any,
    sec: SecretsStore,
    *,
    code: str,
    redirect_uri: str,
    lang: Literal["vi", "en"],
    base_utc: datetime,
    workspace_id: int = 1,
) -> int:
    from videocreator.posting.accounts import upsert_account

    app_id = sec.get("THREADS_APP_ID") or ""
    app_secret = sec.get("THREADS_APP_SECRET") or ""
    if not app_id or not app_secret:
        raise ValueError("Thiếu THREADS_APP_ID hoặc THREADS_APP_SECRET")

    r_tok = client.post(
        THREADS_TOKEN_URL,
        data={
            "client_id": app_id,
            "client_secret": app_secret,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
            "code": code.strip(),
        },
    )
    r_tok.raise_for_status()
    tok_data = r_tok.json() or {}
    short_token = str(tok_data.get("access_token") or "").strip()
    if not short_token:
        err_detail = tok_data.get("error_message") or (tok_data.get("error") or {})
        raise ValueError(f"Threads OAuth không trả về access_token: {err_detail}")

    # Exchange for 60-day long-lived token
    r_long = client.get(
        THREADS_LONG_LIVED_URL,
        params={
            "grant_type": "th_exchange_token",
            "client_secret": app_secret,
            "access_token": short_token,
        },
    )
    if r_long.status_code == 200:
        long_data = r_long.json()
        access_token = str(long_data.get("access_token") or short_token)
        expires_in = int(long_data.get("expires_in") or 5184000)
    else:
        access_token = short_token
        expires_in = 3600

    r_me = client.get(
        THREADS_ME_URL,
        params={"fields": "id,username,name", "access_token": access_token},
    )
    r_me.raise_for_status()
    me_data = r_me.json()
    ext_id = str(me_data.get("id") or tok_data.get("user_id") or "")
    acc_name = str(me_data.get("username") or me_data.get("name") or f"threads_{ext_id}")

    return upsert_account(
        paths,
        platform="threads",
        external_id=ext_id,
        name=acc_name,
        access_token=access_token,
        lang=lang,
        token_expires_at=_expiry_iso(base_utc, expires_in),
        workspace_id=workspace_id,
        secrets_store=sec,
    )


def _tiktok_account_name(client: Any, access_token: str, fallback: str) -> str:
    try:
        r_user = client.get(
            TIKTOK_USER_INFO_URL,
            params={"fields": "open_id,display_name,username"},
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if r_user.status_code != 200:
            return fallback
        u_info = (r_user.json().get("data") or {}).get("user") or {}
        return str(u_info.get("username") or u_info.get("display_name") or fallback)
    except Exception:
        return fallback


def _exchange_tiktok(
    paths: AppPaths,
    client: Any,
    sec: SecretsStore,
    *,
    code: str,
    redirect_uri: str,
    lang: Literal["vi", "en"],
    base_utc: datetime,
    workspace_id: int = 1,
) -> int:
    from videocreator.posting.accounts import upsert_account

    client_key = sec.get("TIKTOK_CLIENT_KEY") or ""
    client_secret = sec.get("TIKTOK_CLIENT_SECRET") or ""
    if not client_key or not client_secret:
        raise ValueError("Thiếu TIKTOK_CLIENT_KEY hoặc TIKTOK_CLIENT_SECRET")

    r_tok = client.post(
        TIKTOK_TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "client_key": client_key,
            "client_secret": client_secret,
            "code": code.strip(),
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        },
    )
    r_tok.raise_for_status()
    tok_data = r_tok.json() or {}
    tok_inner = tok_data.get("data") if isinstance(tok_data.get("data"), dict) else {}
    access_token = str(tok_data.get("access_token") or tok_inner.get("access_token") or "").strip()
    if not access_token:
        err_desc = tok_data.get("error_description") or tok_data.get("error") or "unknown error"
        raise ValueError(f"TikTok OAuth không trả về access_token: {err_desc}")
    refresh_token = str(tok_data.get("refresh_token") or tok_inner.get("refresh_token") or "")
    open_id = str(tok_data.get("open_id") or tok_inner.get("open_id") or "")
    expires_in = int(tok_data.get("expires_in") or tok_inner.get("expires_in") or 86400)

    acc_id = upsert_account(
        paths,
        platform="tiktok",
        external_id=open_id,
        name=_tiktok_account_name(client, access_token, fallback=f"tiktok_{open_id[:8]}"),
        access_token=access_token,
        lang=lang,
        token_expires_at=_expiry_iso(base_utc, expires_in),
        workspace_id=workspace_id,
        secrets_store=sec,
    )
    if not refresh_token:
        return acc_id
    acc_row = query_one(
        paths.db_file,
        "SELECT secret_key FROM accounts WHERE id = ?",
        (acc_id,),
    )
    if acc_row:
        sec.set(f"{acc_row['secret_key']}_REFRESH", refresh_token)
    return acc_id


def _exchange_youtube(
    paths: AppPaths,
    client: Any,
    sec: SecretsStore,
    *,
    code: str,
    redirect_uri: str,
    lang: Literal["vi", "en"],
    base_utc: datetime,
    workspace_id: int = 1,
) -> int:
    from videocreator.posting.accounts import upsert_account

    client_id = sec.get("GOOGLE_CLIENT_ID") or ""
    client_secret = sec.get("GOOGLE_CLIENT_SECRET") or ""
    if not client_id or not client_secret:
        raise ValueError("Thiếu GOOGLE_CLIENT_ID hoặc GOOGLE_CLIENT_SECRET")

    r_tok = client.post(
        YOUTUBE_TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code.strip(),
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        },
    )
    r_tok.raise_for_status()
    tok_data = r_tok.json() or {}
    access_token = str(tok_data.get("access_token") or "").strip()
    if not access_token:
        raise ValueError(
            f"YouTube OAuth không trả về access_token: {tok_data.get('error_description') or tok_data.get('error') or 'unknown'}"
        )
    refresh_token = str(tok_data.get("refresh_token") or "").strip()
    expires_in = int(tok_data.get("expires_in") or 3600)

    r_ch = client.get(
        YOUTUBE_CHANNELS_URL,
        params={"part": "snippet", "mine": "true"},
        headers={"Authorization": f"Bearer {access_token}"},
    )
    channel_id = "youtube_channel"
    channel_name = "YouTube Channel"
    if r_ch.status_code == 200:
        items = (r_ch.json() or {}).get("items") or []
        if items:
            channel_id = str(items[0].get("id") or channel_id)
            snippet = items[0].get("snippet") or {}
            channel_name = str(snippet.get("title") or channel_name)

    acc_id = upsert_account(
        paths,
        platform="youtube",
        external_id=channel_id,
        name=channel_name,
        access_token=access_token,
        lang=lang,
        token_expires_at=_expiry_iso(base_utc, expires_in),
        workspace_id=workspace_id,
        secrets_store=sec,
    )
    if refresh_token:
        acc_row = query_one(
            paths.db_file,
            "SELECT secret_key FROM accounts WHERE id = ?",
            (acc_id,),
        )
        if acc_row:
            sec.set(f"{acc_row['secret_key']}_REFRESH", refresh_token)
    return acc_id


def exchange_code_for_account(
    paths: AppPaths,
    platform: Literal["threads", "tiktok", "youtube"],
    *,
    code: str,
    state: str,
    now_dt: datetime | None = None,
    secrets_store: SecretsStore | None = None,
    http_client: Any = None,
) -> int:
    """Validates CSRF `state`, exchanges `code` for access/refresh tokens, and upserts the `accounts` row."""
    state_data = consume_oauth_state(
        paths.db_file, state, expected_platform=platform, now_dt=now_dt
    )
    exchange = {
        "threads": _exchange_threads,
        "tiktok": _exchange_tiktok,
        "youtube": _exchange_youtube,
    }.get(platform)
    if exchange is None:
        raise ValueError(f"Unsupported OAuth platform: {platform}")

    ws_id = int(state_data.get("workspace_id") or 1)
    own_client = http_client is None
    client = http_client or httpx.Client(timeout=30.0)
    try:
        if platform == "threads":
            return _exchange_threads(
                paths,
                client,
                secrets_store or SecretsStore(paths.secrets_file),
                code=code,
                redirect_uri=str(state_data.get("redirect_uri") or ""),
                lang="en" if state_data.get("lang") == "en" else "vi",
                base_utc=utc_now(now_dt),
                workspace_id=ws_id,
            )
        return exchange(
            paths,
            client,
            secrets_store or SecretsStore(paths.secrets_file),
            code=code,
            redirect_uri=str(state_data.get("redirect_uri") or ""),
            lang="en" if state_data.get("lang") == "en" else "vi",
            base_utc=utc_now(now_dt),
            workspace_id=ws_id,
        )
    finally:
        if own_client:
            client.close()

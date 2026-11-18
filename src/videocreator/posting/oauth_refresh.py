"""Automatic token refresh for Threads and TikTok accounts (Phase 11)."""
from __future__ import annotations
from datetime import datetime, timedelta
from typing import Any

import httpx

from videocreator.db import get_conn, record_audit
from videocreator.paths import AppPaths
from videocreator.posting.oauth import THREADS_REFRESH_URL, TIKTOK_TOKEN_URL
from videocreator.secrets_store import SecretsStore
from videocreator.timeutil import UTC_ISO_FORMAT, parse_iso_utc, utc_now

TOKEN_REFRESH_MARGIN_MINUTES = 10
THREADS_REFRESH_MARGIN = timedelta(days=7)


def _save_new_expiry(
    paths: AppPaths, account_id: int, platform: str, base_utc: datetime, expires_in_s: int
) -> None:
    new_exp_iso = (base_utc + timedelta(seconds=expires_in_s)).strftime(UTC_ISO_FORMAT)
    with get_conn(paths.db_file) as conn:
        conn.execute(
            "UPDATE accounts SET token_expires_at = ? WHERE id = ?",
            (new_exp_iso, account_id),
        )
        record_audit(
            conn,
            actor="system",
            action="account.token_refreshed",
            object_type="account",
            object_id=account_id,
            detail=f"{platform} expires_at={new_exp_iso}",
        )


def _refresh_tiktok(client: Any, sec: SecretsStore, secret_key: str) -> int | None:
    """Stores the new TikTok tokens; returns their lifetime in seconds, or None when not configured."""
    refresh_tok = sec.get(f"{secret_key}_REFRESH")
    client_key = sec.get("TIKTOK_CLIENT_KEY") or ""
    client_secret = sec.get("TIKTOK_CLIENT_SECRET") or ""
    if not refresh_tok or not client_key or not client_secret:
        return None

    resp = client.post(
        TIKTOK_TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "client_key": client_key,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_tok,
        },
    )
    resp.raise_for_status()
    data = resp.json() or {}
    inner = data.get("data") if isinstance(data.get("data"), dict) else {}
    new_access = str(data.get("access_token") or inner.get("access_token") or "").strip()
    if not new_access:
        err_desc = data.get("error_description") or data.get("error") or "unknown error"
        raise ValueError(f"TikTok token refresh missing access_token: {err_desc}")
    new_refresh = str(data.get("refresh_token") or inner.get("refresh_token") or refresh_tok)
    sec.set(secret_key, new_access)
    sec.set(f"{secret_key}_REFRESH", new_refresh)
    return int(data.get("expires_in") or inner.get("expires_in") or 86400)


def _refresh_threads(client: Any, sec: SecretsStore, secret_key: str) -> int | None:
    """Stores the new Threads token; returns its lifetime in seconds, or None when there is no token."""
    cur_tok = sec.get(secret_key)
    if not cur_tok:
        return None
    resp = client.get(
        THREADS_REFRESH_URL,
        params={
            "grant_type": "th_refresh_token",
            "access_token": cur_tok,
        },
    )
    resp.raise_for_status()
    data = resp.json() or {}
    new_access = str(data.get("access_token") or "").strip()
    if not new_access:
        raise ValueError(f"Threads token refresh missing access_token: {data.get('error') or 'unknown error'}")
    sec.set(secret_key, new_access)
    return int(data.get("expires_in") or 5184000)


def refresh_token_if_needed(
    paths: AppPaths,
    account_row: dict[str, Any],
    *,
    now_dt: datetime | None = None,
    secrets_store: SecretsStore | None = None,
    http_client: Any = None,
) -> bool:
    """Refreshes Threads or TikTok token if `token_expires_at` is within threshold (`< 10 min` for TikTok, `< 7 days` for Threads)."""
    platform = str(account_row.get("platform") or "")
    if platform not in ("threads", "tiktok"):
        return False

    exp_dt = parse_iso_utc(account_row.get("token_expires_at"))
    if exp_dt is None:
        return False

    base_utc = utc_now(now_dt)
    threshold = (
        timedelta(minutes=TOKEN_REFRESH_MARGIN_MINUTES) if platform == "tiktok" else THREADS_REFRESH_MARGIN
    )
    if (exp_dt - base_utc) > threshold:
        return False

    sec = secrets_store or SecretsStore(paths.secrets_file)
    secret_key = str(account_row["secret_key"])
    refresh = _refresh_tiktok if platform == "tiktok" else _refresh_threads

    own_client = http_client is None
    client = http_client or httpx.Client(timeout=30.0)
    try:
        expires_in_s = refresh(client, sec, secret_key)
        if expires_in_s is None:
            return False
        _save_new_expiry(paths, int(account_row["id"]), platform, base_utc, expires_in_s)
        return True
    finally:
        if own_client:
            client.close()

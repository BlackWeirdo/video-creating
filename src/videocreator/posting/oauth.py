"""Unified OAuth 2.0 flow and automatic token refresh for Threads and TikTok (Phase 11)."""
from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlencode

import httpx

from videocreator.db import get_conn, query_one, record_audit
from videocreator.paths import AppPaths
from videocreator.secrets_store import SecretsStore

OAUTH_STATE_TTL_MINUTES = 10
TOKEN_REFRESH_MARGIN_MINUTES = 10

THREADS_AUTH_URL = "https://threads.net/oauth/authorize"
THREADS_TOKEN_URL = "https://graph.threads.net/oauth/access_token"
THREADS_LONG_LIVED_URL = "https://graph.threads.net/access_token"
THREADS_REFRESH_URL = "https://graph.threads.net/refresh_access_token"
THREADS_ME_URL = "https://graph.threads.net/v1.0/me"

TIKTOK_AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
TIKTOK_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
TIKTOK_USER_INFO_URL = "https://open.tiktokapis.com/v2/user/info/"


def _parse_iso_utc(iso_str: str | None) -> datetime | None:
    if not iso_str:
        return None
    try:
        clean = str(iso_str).strip()
        if clean.endswith("Z"):
            clean = clean[:-1] + "+00:00"
        dt = datetime.fromisoformat(clean)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def build_authorize_url(
    paths: AppPaths,
    platform: Literal["threads", "tiktok"],
    *,
    redirect_uri: str,
    lang: Literal["vi", "en"] = "vi",
    now_dt: datetime | None = None,
    secrets_store: SecretsStore | None = None,
) -> tuple[str, str]:
    """Generates a single-use CSRF `state` (10 min TTL) and returns `(authorize_url, state)`."""
    sec = secrets_store or SecretsStore(paths.secrets_file)
    base_utc = (now_dt or datetime.now(timezone.utc)).astimezone(timezone.utc)
    expires_utc = base_utc + timedelta(minutes=OAUTH_STATE_TTL_MINUTES)

    state = secrets.token_urlsafe(24)
    payload = {
        "platform": platform,
        "redirect_uri": redirect_uri,
        "lang": lang,
        "expires_at": expires_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    with get_conn(paths.db_file) as conn:
        conn.execute(
            """
            INSERT INTO settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (f"oauth_state:{state}", json.dumps(payload)),
        )

    if platform == "threads":
        client_id = sec.get("THREADS_APP_ID") or ""
        if not client_id:
            raise ValueError("Chưa cấu hình THREADS_APP_ID trong Settings / Secrets")
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": "threads_basic,threads_content_publish",
            "response_type": "code",
            "state": state,
        }
        return f"{THREADS_AUTH_URL}?{urlencode(params)}", state

    if platform == "tiktok":
        client_key = sec.get("TIKTOK_CLIENT_KEY") or ""
        if not client_key:
            raise ValueError("Chưa cấu hình TIKTOK_CLIENT_KEY trong Settings / Secrets")
        params = {
            "client_key": client_key,
            "redirect_uri": redirect_uri,
            "scope": "user.info.basic,video.upload,video.publish",
            "response_type": "code",
            "state": state,
        }
        return f"{TIKTOK_AUTH_URL}?{urlencode(params)}", state

    raise ValueError(f"Unsupported OAuth platform: {platform}")


def consume_oauth_state(
    db_file: Path,
    state: str,
    *,
    expected_platform: str | None = None,
    now_dt: datetime | None = None,
) -> dict[str, Any]:
    """Validates and deletes a one-time OAuth `state` token; raises `ValueError` if invalid or expired."""
    clean_state = (state or "").strip()
    if not clean_state:
        raise ValueError("Thiếu tham số state OAuth")

    key = f"oauth_state:{clean_state}"
    with get_conn(db_file) as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            raise ValueError("State OAuth không hợp lệ hoặc đã được sử dụng")
        conn.execute("DELETE FROM settings WHERE key = ?", (key,))

    try:
        data = json.loads(str(row["value"]))
    except Exception as exc:
        raise ValueError("Dữ liệu state OAuth bị hỏng") from exc

    if expected_platform and data.get("platform") != expected_platform:
        raise ValueError(
            f"State OAuth thuộc nền tảng '{data.get('platform')}', không khớp '{expected_platform}'"
        )

    base_utc = (now_dt or datetime.now(timezone.utc)).astimezone(timezone.utc)
    exp_dt = _parse_iso_utc(data.get("expires_at"))
    if exp_dt is None or base_utc > exp_dt:
        raise ValueError("State OAuth đã hết hạn (quá 10 phút)")

    return data


def exchange_code_for_account(
    paths: AppPaths,
    platform: Literal["threads", "tiktok"],
    *,
    code: str,
    state: str,
    now_dt: datetime | None = None,
    secrets_store: SecretsStore | None = None,
    http_client: Any = None,
) -> int:
    """Validates CSRF `state`, exchanges `code` for access/refresh tokens, and upserts the `accounts` row."""
    from videocreator.api.routes_posting import upsert_account

    state_data = consume_oauth_state(
        paths.db_file, state, expected_platform=platform, now_dt=now_dt
    )
    redirect_uri = str(state_data.get("redirect_uri") or "")
    lang: Literal["vi", "en"] = "en" if state_data.get("lang") == "en" else "vi"
    base_utc = (now_dt or datetime.now(timezone.utc)).astimezone(timezone.utc)
    sec = secrets_store or SecretsStore(paths.secrets_file)

    own_client = http_client is None
    client = http_client or httpx.Client(timeout=30.0)
    try:
        if platform == "threads":
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
            tok_data = r_tok.json()
            short_token = str(tok_data["access_token"])

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
            exp_iso = (base_utc + timedelta(seconds=expires_in)).strftime("%Y-%m-%dT%H:%M:%SZ")

            return upsert_account(
                paths,
                platform="threads",
                external_id=ext_id,
                name=acc_name,
                access_token=access_token,
                lang=lang,
                token_expires_at=exp_iso,
                secrets_store=sec,
            )

        if platform == "tiktok":
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
            tok_data = r_tok.json()
            access_token = str(tok_data["access_token"])
            refresh_token = str(tok_data.get("refresh_token") or "")
            open_id = str(tok_data.get("open_id") or "")
            expires_in = int(tok_data.get("expires_in") or 86400)

            acc_name = f"tiktok_{open_id[:8]}"
            try:
                r_user = client.get(
                    TIKTOK_USER_INFO_URL,
                    params={"fields": "open_id,display_name,username"},
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                if r_user.status_code == 200:
                    u_info = (r_user.json().get("data") or {}).get("user") or {}
                    acc_name = str(
                        u_info.get("username")
                        or u_info.get("display_name")
                        or acc_name
                    )
            except Exception:
                pass

            exp_iso = (base_utc + timedelta(seconds=expires_in)).strftime("%Y-%m-%dT%H:%M:%SZ")
            acc_id = upsert_account(
                paths,
                platform="tiktok",
                external_id=open_id,
                name=acc_name,
                access_token=access_token,
                lang=lang,
                token_expires_at=exp_iso,
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

        raise ValueError(f"Unsupported OAuth platform: {platform}")
    finally:
        if own_client:
            client.close()


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

    exp_dt = _parse_iso_utc(account_row.get("token_expires_at"))
    if exp_dt is None:
        return False

    base_utc = (now_dt or datetime.now(timezone.utc)).astimezone(timezone.utc)
    threshold = (
        timedelta(minutes=TOKEN_REFRESH_MARGIN_MINUTES)
        if platform == "tiktok"
        else timedelta(days=7)
    )
    if (exp_dt - base_utc) > threshold:
        return False

    sec = secrets_store or SecretsStore(paths.secrets_file)
    secret_key = str(account_row["secret_key"])
    acc_id = int(account_row["id"])

    own_client = http_client is None
    client = http_client or httpx.Client(timeout=30.0)
    try:
        if platform == "tiktok":
            refresh_tok = sec.get(f"{secret_key}_REFRESH")
            client_key = sec.get("TIKTOK_CLIENT_KEY") or ""
            client_secret = sec.get("TIKTOK_CLIENT_SECRET") or ""
            if not refresh_tok or not client_key or not client_secret:
                return False

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
            data = resp.json()
            new_access = str(data["access_token"])
            new_refresh = str(data.get("refresh_token") or refresh_tok)
            expires_in = int(data.get("expires_in") or 86400)
            new_exp_iso = (base_utc + timedelta(seconds=expires_in)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )

            sec.set(secret_key, new_access)
            sec.set(f"{secret_key}_REFRESH", new_refresh)
            with get_conn(paths.db_file) as conn:
                conn.execute(
                    "UPDATE accounts SET token_expires_at = ? WHERE id = ?",
                    (new_exp_iso, acc_id),
                )
                record_audit(
                    conn,
                    actor="system",
                    action="account.token_refreshed",
                    object_type="account",
                    object_id=acc_id,
                    detail=f"tiktok expires_at={new_exp_iso}",
                )
            return True

        if platform == "threads":
            cur_tok = sec.get(secret_key)
            if not cur_tok:
                return False
            resp = client.get(
                THREADS_REFRESH_URL,
                params={
                    "grant_type": "th_refresh_token",
                    "access_token": cur_tok,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            new_access = str(data["access_token"])
            expires_in = int(data.get("expires_in") or 5184000)
            new_exp_iso = (base_utc + timedelta(seconds=expires_in)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )

            sec.set(secret_key, new_access)
            with get_conn(paths.db_file) as conn:
                conn.execute(
                    "UPDATE accounts SET token_expires_at = ? WHERE id = ?",
                    (new_exp_iso, acc_id),
                )
                record_audit(
                    conn,
                    actor="system",
                    action="account.token_refreshed",
                    object_type="account",
                    object_id=acc_id,
                    detail=f"threads expires_at={new_exp_iso}",
                )
            return True

        return False
    finally:
        if own_client:
            client.close()

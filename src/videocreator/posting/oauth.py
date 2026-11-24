"""Unified OAuth 2.0 flow and automatic token refresh for Threads and TikTok (Phase 11)."""
from __future__ import annotations
import json
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlencode

from videocreator.db import get_conn
from videocreator.paths import AppPaths
from videocreator.secrets_store import SecretsStore
from videocreator.timeutil import UTC_ISO_FORMAT, parse_iso_utc, utc_now

OAUTH_STATE_TTL_MINUTES = 10

THREADS_AUTH_URL = "https://threads.net/oauth/authorize"
THREADS_TOKEN_URL = "https://graph.threads.net/oauth/access_token"
THREADS_LONG_LIVED_URL = "https://graph.threads.net/access_token"
THREADS_REFRESH_URL = "https://graph.threads.net/refresh_access_token"
THREADS_ME_URL = "https://graph.threads.net/v1.0/me"

TIKTOK_AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
TIKTOK_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
TIKTOK_USER_INFO_URL = "https://open.tiktokapis.com/v2/user/info/"

YOUTUBE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
YOUTUBE_TOKEN_URL = "https://oauth2.googleapis.com/token"
YOUTUBE_CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"
YOUTUBE_SCOPE = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly"


def build_authorize_url(
    paths: AppPaths,
    platform: Literal["threads", "tiktok", "youtube"],
    *,
    redirect_uri: str,
    lang: Literal["vi", "en"] = "vi",
    workspace_id: int = 1,
    now_dt: datetime | None = None,
    secrets_store: SecretsStore | None = None,
) -> tuple[str, str]:
    """Generates a single-use CSRF `state` (10 min TTL) and returns `(authorize_url, state)`."""
    sec = secrets_store or SecretsStore(paths.secrets_file)
    base_utc = utc_now(now_dt)
    expires_utc = base_utc + timedelta(minutes=OAUTH_STATE_TTL_MINUTES)

    state = secrets.token_urlsafe(24)
    payload = {
        "platform": platform,
        "redirect_uri": redirect_uri,
        "lang": lang,
        "workspace_id": int(workspace_id),
        "expires_at": expires_utc.strftime(UTC_ISO_FORMAT),
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

    if platform == "youtube":
        client_id = sec.get("GOOGLE_CLIENT_ID") or ""
        if not client_id:
            raise ValueError("Chưa cấu hình GOOGLE_CLIENT_ID trong Settings / Secrets")
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": YOUTUBE_SCOPE,
            "response_type": "code",
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        return f"{YOUTUBE_AUTH_URL}?{urlencode(params)}", state

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

    base_utc = utc_now(now_dt)
    exp_dt = parse_iso_utc(data.get("expires_at"))
    if exp_dt is None or base_utc > exp_dt:
        raise ValueError("State OAuth đã hết hạn (quá 10 phút)")

    return data

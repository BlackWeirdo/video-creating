"""Real SQLite tests for OAuth authorize URL generation, single-use CSRF state validation, token refresh, and TikTok inbox confirmation (Phase 11)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from videocreator.api.routes_posting import upsert_account
from videocreator.app import create_app
from videocreator.db import get_conn, query_one
from videocreator.posting.oauth import (
    build_authorize_url,
    consume_oauth_state,
    exchange_code_for_account,
    refresh_token_if_needed,
)
from videocreator.posting.service import confirm_user_action_post
from videocreator.secrets_store import SecretsStore


class _FakeHttpResponse:
    def __init__(self, status_code: int, payload: dict[str, Any]) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeOAuthHttpClient:
    def __init__(self) -> None:
        self.post_calls: list[tuple[str, Any]] = []
        self.get_calls: list[tuple[str, Any]] = []

    def post(self, url: str, **kwargs: Any) -> _FakeHttpResponse:
        self.post_calls.append((url, kwargs))
        if "tiktokapis.com" in url:
            return _FakeHttpResponse(
                200,
                {
                    "access_token": "tt_access_token_fresh_999",
                    "refresh_token": "tt_refresh_token_fresh_999",
                    "open_id": "tt_open_id_888",
                    "expires_in": 86400,
                },
            )
        return _FakeHttpResponse(
            200,
            {"access_token": "th_short_token_111", "user_id": "th_user_777"},
        )

    def get(self, url: str, **kwargs: Any) -> _FakeHttpResponse:
        self.get_calls.append((url, kwargs))
        if "access_token" in url and "refresh" not in url:
            return _FakeHttpResponse(
                200,
                {"access_token": "th_long_lived_token_222", "expires_in": 5184000},
            )
        if "refresh_access_token" in url:
            return _FakeHttpResponse(
                200,
                {"access_token": "th_refreshed_token_333", "expires_in": 5184000},
            )
        if "/me" in url:
            return _FakeHttpResponse(
                200,
                {"id": "th_user_777", "username": "silver_craft_threads"},
            )
        return _FakeHttpResponse(
            200,
            {"data": {"user": {"open_id": "tt_open_id_888", "username": "silver_craft_tt"}}},
        )

    def close(self) -> None:
        pass


@pytest.mark.local
def test_oauth_authorize_url_csrf_state_and_code_exchange(tmp_path: Path) -> None:
    app = create_app(data_dir=tmp_path, start_worker=False)
    paths = app.state.paths
    secrets: SecretsStore = app.state.secrets

    secrets.set("THREADS_APP_ID", "th_app_123456")
    secrets.set("THREADS_APP_SECRET", "th_sec_abcdef")
    secrets.set("TIKTOK_CLIENT_KEY", "tt_key_654321")
    secrets.set("TIKTOK_CLIENT_SECRET", "tt_sec_fedcba")

    t0 = datetime(2026, 11, 14, 10, 0, 0, tzinfo=timezone.utc)

    # 1. Generate Threads authorize URL and verify parameters
    th_url, th_state = build_authorize_url(
        paths,
        "threads",
        redirect_uri="http://127.0.0.1:8765/oauth/threads/callback",
        lang="vi",
        now_dt=t0,
        secrets_store=secrets,
    )
    parsed_th = urlparse(th_url)
    qs_th = parse_qs(parsed_th.query)
    assert parsed_th.netloc == "threads.net"
    assert qs_th["client_id"] == ["th_app_123456"]
    assert qs_th["scope"] == ["threads_basic,threads_content_publish"]
    assert qs_th["state"] == [th_state]

    # 2. Wrong state is rejected
    with pytest.raises(ValueError, match="không hợp lệ"):
        consume_oauth_state(paths.db_file, "wrong_csrf_state", expected_platform="threads", now_dt=t0)

    # 3. Expired state (> 10 minutes) is rejected
    _, exp_state = build_authorize_url(
        paths,
        "tiktok",
        redirect_uri="http://127.0.0.1:8765/oauth/tiktok/callback",
        now_dt=t0,
        secrets_store=secrets,
    )
    with pytest.raises(ValueError, match="hết hạn"):
        consume_oauth_state(
            paths.db_file,
            exp_state,
            expected_platform="tiktok",
            now_dt=t0 + timedelta(minutes=11),
        )

    # 4. Exchange valid state + code for Threads account; state cannot be reused a second time
    http_client = _FakeOAuthHttpClient()
    acc_th_id = exchange_code_for_account(
        paths,
        "threads",
        code="auth_code_threads_1",
        state=th_state,
        now_dt=t0 + timedelta(minutes=1),
        secrets_store=secrets,
        http_client=http_client,
    )
    assert acc_th_id > 0
    th_row = query_one(paths.db_file, "SELECT * FROM accounts WHERE id = ?", (acc_th_id,))
    assert th_row is not None
    assert th_row["platform"] == "threads"
    assert th_row["name"] == "silver_craft_threads"
    assert secrets.get(str(th_row["secret_key"])) == "th_long_lived_token_222"

    # Reusing the same state a second time fails (one-time use)
    with pytest.raises(ValueError, match="đã được sử dụng"):
        consume_oauth_state(paths.db_file, th_state, expected_platform="threads", now_dt=t0)


@pytest.mark.local
def test_token_refresh_by_expiry_and_tiktok_inbox_confirmation(tmp_path: Path) -> None:
    app = create_app(data_dir=tmp_path, start_worker=False)
    paths = app.state.paths
    secrets: SecretsStore = app.state.secrets
    secrets.set("TIKTOK_CLIENT_KEY", "tt_key_654321")
    secrets.set("TIKTOK_CLIENT_SECRET", "tt_sec_fedcba")

    t0 = datetime(2026, 11, 14, 12, 0, 0, tzinfo=timezone.utc)
    # Token expires in 5 minutes (< 10 min threshold -> must refresh)
    exp_soon_iso = (t0 + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")

    acc_id = upsert_account(
        paths,
        platform="tiktok",
        external_id="tt_open_id_888",
        name="silver_craft_tt",
        access_token="tt_old_access_token_111",
        token_expires_at=exp_soon_iso,
        secrets_store=secrets,
    )
    acc_row = query_one(paths.db_file, "SELECT * FROM accounts WHERE id = ?", (acc_id,))
    assert acc_row is not None
    secrets.set(f"{acc_row['secret_key']}_REFRESH", "tt_old_refresh_token_111")

    http_client = _FakeOAuthHttpClient()
    # When token still has 2 hours left (now_dt = t0 - 2h), refresh_token_if_needed returns False
    assert (
        refresh_token_if_needed(
            paths,
            acc_row,
            now_dt=t0 - timedelta(hours=2),
            secrets_store=secrets,
            http_client=http_client,
        )
        is False
    )

    # At t0 (5 min before expiry), refresh_token_if_needed refreshes and updates DB + SecretsStore
    assert (
        refresh_token_if_needed(
            paths,
            acc_row,
            now_dt=t0,
            secrets_store=secrets,
            http_client=http_client,
        )
        is True
    )
    assert secrets.get(str(acc_row["secret_key"])) == "tt_access_token_fresh_999"
    updated_acc = query_one(paths.db_file, "SELECT token_expires_at FROM accounts WHERE id = ?", (acc_id,))
    assert updated_acc is not None
    assert updated_acc["token_expires_at"] != exp_soon_iso

    # TikTok inbox post in needs_user_action transitions to posted when user clicks "Đã đăng"
    with get_conn(paths.db_file) as conn:
        conn.execute("INSERT INTO videos (id, status) VALUES (20, 'scheduled')")
        conn.execute(
            """
            INSERT INTO posts (id, video_id, account_id, status, scheduled_at, external_post_id)
            VALUES (200, 20, ?, 'needs_user_action', '2026-11-14T12:00:00Z', 'pub_inbox_123')
            """,
            (acc_id,),
        )

    assert (
        confirm_user_action_post(
            paths.db_file,
            200,
            permalink="https://www.tiktok.com/@silver_craft_tt/video/999",
        )
        is True
    )
    p_after = query_one(paths.db_file, "SELECT status, permalink FROM posts WHERE id = 200")
    assert p_after is not None
    assert p_after["status"] == "posted"
    assert p_after["permalink"] == "https://www.tiktok.com/@silver_craft_tt/video/999"

    # Also verify /oauth/tiktok/start route redirects to tiktok.com
    with TestClient(app) as client:
        resp = client.get("/oauth/tiktok/start?lang=vi", follow_redirects=False)
        assert resp.status_code == 302
        assert "tiktok.com/v2/auth/authorize/" in resp.headers["location"]

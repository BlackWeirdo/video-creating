"""Real SQLite migration, configuration, and app persistence tests (no mocks)."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from videocreator.app import create_app
from videocreator.config import load_settings, save_settings
from videocreator.db import execute, get_conn, get_user_version, migrate, query_one
from videocreator.paths import get_paths

pytestmark = pytest.mark.local


def test_migrate_creates_schema_and_is_idempotent(tmp_path: Path) -> None:
    db_file = tmp_path / "app.db"
    v1 = migrate(db_file)
    assert v1 >= 1

    v2 = migrate(db_file)
    assert v2 == v1

    with get_conn(db_file) as conn:
        assert get_user_version(conn) == v1
        journal = conn.execute("PRAGMA journal_mode;").fetchone()[0]
        assert str(journal).lower() == "wal"

        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        expected_tables = {
            "products",
            "footage",
            "shots",
            "assets",
            "videos",
            "accounts",
            "posts",
            "jobs",
            "ai_usage",
            "provider_state",
            "audit_log",
            "settings",
        }
        assert expected_tables.issubset(tables)


def test_config_round_trip(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.toml"
    cfg = load_settings(cfg_file)
    assert cfg_file.exists()
    assert cfg.role == "server"
    assert cfg.budget.daily_usd == 5.0

    cfg.role = "client"
    cfg.budget.daily_usd = 7.5
    save_settings(cfg_file, cfg)

    reloaded = load_settings(cfg_file)
    assert reloaded.role == "client"
    assert reloaded.budget.daily_usd == 7.5


def test_app_dashboard_and_persistence_across_restarts(tmp_path: Path) -> None:
    paths = get_paths(tmp_path)
    migrate(paths.db_file)
    execute(
        paths.db_file,
        "INSERT INTO footage (path, sha256, status) VALUES (?, ?, 'analysed')",
        ("media/footage/1.mp4", "abc123sha256"),
    )
    execute(
        paths.db_file,
        "INSERT INTO videos (status, engine) VALUES ('pending_approval', 'ffmpeg')",
    )

    app1 = create_app(tmp_path, start_worker=False)
    with TestClient(app1) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"

        home = client.get("/")
        assert home.status_code == 200
        assert "Trang chủ" in home.text

        resp = client.post(
            "/settings/config",
            data={
                "role": "server",
                "host": "127.0.0.1",
                "port": "8765",
                "daily_usd": "6.25",
                "generative_daily_usd": "15.0",
                "studio_daily_usd": "10.0",
                "api_fallback": "never",
                "offpeak_hours": "23:00-06:00",
                "vision_routes": "claude_cli, gemini_api",
                "writer_routes": "claude_cli, claude_api",
                "checker_routes": "claude_cli, claude_api",
                "studio_routes": "claude_cli, claude_api",
                "timezone_name": "Asia/Ho_Chi_Minh",
                "schedule_auto": "true",
                "schedule_slots": "09:00, 18:00",
                "allowed_chat_ids": "-100123456",
                "approver_user_ids": "111, 222",
                "quiet_hours": "22:00-07:00",
                "r2_bucket": "jewelry-videos",
                "r2_public_base": "https://cdn.example.com",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 303

    # Simulate app close and reopen on the same data directory
    app2 = create_app(tmp_path, start_worker=False)
    with TestClient(app2) as client2:
        settings_page = client2.get("/settings")
        assert settings_page.status_code == 200
        assert "jewelry-videos" in settings_page.text

    cfg = load_settings(paths.config_file)
    assert cfg.budget.daily_usd == 6.25
    assert cfg.ai.policy.api_fallback == "never"
    assert cfg.telegram.approver_user_ids == [111, 222]

    video_row = query_one(paths.db_file, "SELECT status FROM videos WHERE id = 1")
    assert video_row is not None
    assert video_row["status"] == "pending_approval"


def test_single_instance_lock_and_non_localhost_guard(tmp_path: Path) -> None:
    from videocreator.__main__ import SingleInstanceLock, main

    lock_file = tmp_path / "instance.lock"
    mutex_name = f"Local\\VideoCreatorTestMutex_{tmp_path.name}"
    lock1 = SingleInstanceLock(lock_file, mutex_name=mutex_name)
    lock2 = SingleInstanceLock(lock_file, mutex_name=mutex_name)

    assert lock1.acquire() is True
    try:
        assert lock2.acquire() is False
    finally:
        lock1.release()

    assert lock2.acquire() is True
    lock2.release()

    # Binding outside 127.0.0.1 without UI_PASSWORD must be rejected (NFR-SEC-02)
    rc = main(["--headless", "--host", "0.0.0.0", "--port", "18765", "--data-dir", str(tmp_path)])
    assert rc == 2


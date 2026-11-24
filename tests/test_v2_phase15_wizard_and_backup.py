"""Tests for Phase 15: First-Run Welcome Wizard & Encrypted .vcx Backup/Restore API."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from videocreator.app import create_app
from videocreator.paths import get_paths
from videocreator.secrets_store import SecretsStore

pytestmark = pytest.mark.local


def test_onboarding_wizard_lifecycle_and_secret_redaction(tmp_path: Path) -> None:
    paths = get_paths(tmp_path / "machine_a")
    app = create_app(paths.data_dir)
    with TestClient(app) as client:
        st0 = client.get("/api/v1/onboarding/status")
        assert st0.status_code == 200
        d0 = st0.json()
        assert d0["wizard_completed"] is False
        assert d0["runtime"]["ffmpeg_ready"] is True
        assert d0["runtime"]["ffprobe_ready"] is True
        assert d0["runtime"]["node_ready"] is True

        comp = client.post(
            "/api/v1/onboarding/complete",
            json={
                "workspace": {
                    "mode": "create",
                    "name": "Bạc S925 Chính Hãng",
                    "niche": "jewelry",
                    "content_policy": "strict_footage",
                    "approval_mode": "single",
                    "default_aspect_ratio": "9:16",
                },
                "daily_usd": 12.5,
                "api_fallback": "auto",
                "timezone": "Asia/Ho_Chi_Minh",
                "vi_provider": "local",
                "vi_voice": "vi-VN-HoaiMyNeural-Female",
                "secrets": {
                    "GEMINI_API_KEY": "AIza_wizard_test_secret_xyz",
                },
                "pooled_keys": [
                    {
                        "provider": "gemini",
                        "raw_secret": "AIza_pool_second_key_888",
                        "label": "Gemini Backup Pool",
                        "priority": 10,
                    }
                ],
            },
        )
        assert comp.status_code == 200, comp.text
        d1 = comp.json()
        assert d1["wizard_completed"] is True
        assert d1["active_workspace"]["name"] == "Bạc S925 Chính Hãng"
        assert d1["active_workspace"]["content_policy"] == "strict_footage"
        assert "GEMINI_API_KEY" in d1["configured_secrets"]
        assert d1["key_pool_count"] == 1
        assert d1["defaults"]["daily_usd"] == 12.5
        # Ensure raw secret values are never leaked into onboarding JSON response
        dumped = json.dumps(d1)
        assert "AIza_wizard_test_secret_xyz" not in dumped
        assert "AIza_pool_second_key_888" not in dumped

        rst = client.post("/api/v1/onboarding/reset")
        assert rst.status_code == 200
        assert rst.json()["wizard_completed"] is False


def test_vcx_backup_export_and_cross_machine_restore_api(tmp_path: Path) -> None:
    paths_a = get_paths(tmp_path / "machine_a")
    app_a = create_app(paths_a.data_dir)
    with TestClient(app_a) as client_a:
        client_a.post(
            "/api/v1/onboarding/complete",
            json={
                "workspace": {
                    "mode": "create",
                    "name": "Podcast & Tin tức V2",
                    "content_policy": "full_ai",
                    "default_aspect_ratio": "16:9",
                },
                "daily_usd": 9.0,
                "secrets": {
                    "GEMINI_API_KEY": "AIza_cross_machine_secret_001",
                    "TELEGRAM_BOT_TOKEN": "999888:TG-BOT-TOKEN",
                },
            },
        )
        client_a.post(
            "/api/v1/workflows",
            json={
                "name": "Portable Workflow V2",
                "description": "Migrated via .vcx",
                "nodes": [{"id": "n1", "type": "voice_node", "data": {"label": "Voice"}}],
                "edges": [],
            },
        )

        sum_a = client_a.get("/api/v1/backup/summary").json()
        assert sum_a["workspaces"] >= 2
        assert sum_a["workflows"] >= 1
        assert sum_a["secrets_count"] >= 2

        exp = client_a.post(
            "/api/v1/backup/export",
            json={"password": "MigratePassword#2026", "save_copy": True},
        )
        assert exp.status_code == 200
        vcx_bytes = exp.content
        assert len(vcx_bytes) > 500
        assert len(list(paths_a.backups_dir.glob("*.vcx"))) == 1

    # Fresh machine B with an existing secret that must survive a wrong-password attack
    paths_b = get_paths(tmp_path / "machine_b")
    app_b = create_app(paths_b.data_dir)
    with TestClient(app_b) as client_b:
        sec_b: SecretsStore = app_b.state.secrets
        sec_b.set("EXISTING_LOCAL_KEY", "untouched_value_123")

        bad = client_b.post(
            "/api/v1/backup/restore",
            files={"file": ("backup.vcx", vcx_bytes, "application/octet-stream")},
            data={"password": "WrongPassword!", "as_server": "true"},
        )
        assert bad.status_code == 400
        assert sec_b.get("EXISTING_LOCAL_KEY") == "untouched_value_123"
        assert sec_b.get("GEMINI_API_KEY") is None
        assert list(paths_b.backups_dir.glob("pre-restore-*.vcx")) == []

        ok = client_b.post(
            "/api/v1/backup/restore",
            files={"file": ("backup.vcx", vcx_bytes, "application/octet-stream")},
            data={"password": "MigratePassword#2026", "as_server": "true"},
        )
        assert ok.status_code == 200, ok.text
        body = ok.json()
        assert body["restored"] is True
        assert body["role"] == "server"
        assert body["pre_restore_backup"].startswith("pre-restore-")
        assert (paths_b.backups_dir / body["pre_restore_backup"]).is_file()
        assert body["onboarding"]["wizard_completed"] is True
        assert sec_b.get("GEMINI_API_KEY") == "AIza_cross_machine_secret_001"
        assert sec_b.get("TELEGRAM_BOT_TOKEN") == "999888:TG-BOT-TOKEN"

        voices_cat = client_b.get("/api/v1/voices").json()["catalog"]
        assert all(v["provider"] != "local" for v in voices_cat)

        wfs = client_b.get("/api/v1/workflows").json()["workflows"]
        assert any(w["name"] == "Portable Workflow V2" for w in wfs)

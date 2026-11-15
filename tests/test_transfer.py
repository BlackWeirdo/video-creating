"""Real SQLite + FastAPI tests for encrypted .vcx config export/import and non-localhost Basic Auth (Phase 08)."""
from __future__ import annotations

import base64
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from videocreator.app import create_app
from videocreator.config import load_settings, save_settings
from videocreator.db import migrate
from videocreator.paths import get_paths
from videocreator.products import create_product, list_products
from videocreator.secrets_store import SecretsStore
from videocreator.transfer import ExportPasswordError, export_config_bundle, import_config_bundle


@pytest.mark.local
def test_export_and_import_vcx_round_trip_and_wrong_password_guard(tmp_path: Path) -> None:
    src_dir = tmp_path / "machine_a"
    dst_dir = tmp_path / "machine_b"
    paths_a = get_paths(src_dir)
    paths_b = get_paths(dst_dir)
    migrate(paths_a.db_file)
    migrate(paths_b.db_file)

    # Populate machine A with config, product in DB, and secrets
    cfg_a = load_settings(paths_a.config_file)
    cfg_a.role = "server"
    cfg_a.budget.daily_usd = 7.5
    save_settings(paths_a.config_file, cfg_a)

    create_product(paths_a.db_file, name="Nhẫn Bạc Chuyển Máy", material="Bạc S925")
    sec_a = SecretsStore(paths_a.secrets_file)
    sec_a.set("GEMINI_API_KEY", "AIza_secret_test_key_999")
    sec_a.set("TELEGRAM_BOT_TOKEN", "123456:ABC-DEF")

    # Seed machine B with an existing secret to verify wrong password does not overwrite it
    sec_b = SecretsStore(paths_b.secrets_file)
    sec_b.set("EXISTING_KEY", "keep_me_safe")

    vcx_file = tmp_path / "backup.vcx"
    export_config_bundle(paths_a, "StrongPass!23", vcx_file, secrets_store=sec_a)
    assert vcx_file.exists() and vcx_file.stat().st_size > 200

    # 1. Wrong password must raise ExportPasswordError and leave machine B untouched
    with pytest.raises(ExportPasswordError):
        import_config_bundle(paths_b, vcx_file, "WrongPassword", secrets_store=sec_b)
    assert sec_b.get("EXISTING_KEY") == "keep_me_safe"
    assert sec_b.get("GEMINI_API_KEY") is None

    # 2. Correct password with default as_server=False -> sets role='client' (FR-OPS-03)
    import_config_bundle(
        paths_b, vcx_file, "StrongPass!23", as_server=False, secrets_store=sec_b
    )
    cfg_b = load_settings(paths_b.config_file)
    assert cfg_b.role == "client"
    assert cfg_b.budget.daily_usd == 7.5
    assert sec_b.get("GEMINI_API_KEY") == "AIza_secret_test_key_999"
    assert sec_b.get("TELEGRAM_BOT_TOKEN") == "123456:ABC-DEF"
    prods_b = list_products(paths_b.db_file)
    assert len(prods_b) == 1
    assert prods_b[0]["name"] == "Nhẫn Bạc Chuyển Máy"

    # 3. Importing with as_server=True keeps role='server'
    import_config_bundle(
        paths_b, vcx_file, "StrongPass!23", as_server=True, secrets_store=sec_b
    )
    assert load_settings(paths_b.config_file).role == "server"


@pytest.mark.local
def test_non_localhost_basic_auth_middleware(tmp_path: Path) -> None:
    app = create_app(data_dir=tmp_path, start_worker=False)
    paths = app.state.paths
    secrets: SecretsStore = app.state.secrets

    # Bind to 0.0.0.0 and set UI_PASSWORD
    cfg = load_settings(paths.config_file)
    cfg.host = "0.0.0.0"
    save_settings(paths.config_file, cfg)
    secrets.set("UI_PASSWORD", "MyLanPass2026")

    with TestClient(app) as client:
        # Health endpoint remains accessible
        assert client.get("/health").status_code == 200

        # Unauthenticated request to UI -> 401
        r_unauth = client.get("/")
        assert r_unauth.status_code == 401
        assert "Basic" in r_unauth.headers.get("www-authenticate", "")

        # Wrong password -> 401
        bad_token = base64.b64encode(b"admin:wrong").decode("ascii")
        assert client.get("/", headers={"Authorization": f"Basic {bad_token}"}).status_code == 401

        # Correct password -> 200
        ok_token = base64.b64encode(b"admin:MyLanPass2026").decode("ascii")
        r_ok = client.get("/", headers={"Authorization": f"Basic {ok_token}"})
        assert r_ok.status_code == 200
        assert "Video Creator" in r_ok.text


@pytest.mark.local
def test_bind_host_override_enforces_auth(tmp_path: Path) -> None:
    # config.toml says localhost, but the process actually binds 0.0.0.0 (--host flag).
    app = create_app(data_dir=tmp_path, start_worker=False, bind_host="0.0.0.0")
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/").status_code == 401

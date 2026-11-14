"""Real DPAPI secrets store and log redaction tests (no mocks)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from videocreator.app import create_app
from videocreator.logging_setup import setup_logging
from videocreator.secrets_store import SecretsStore

pytestmark = pytest.mark.local


def test_secrets_round_trip_and_encrypted_on_disk(tmp_path: Path) -> None:
    secrets_file = tmp_path / "secrets.bin"
    store = SecretsStore(secrets_file)

    secret_val = "sk-ant-super-secret-token-987654321"
    store.set("ANTHROPIC_API_KEY", secret_val)
    store.set("TELEGRAM_BOT_TOKEN", "123456:ABCDEF-secret-bot-token")

    # Re-open from disk with a fresh instance
    store2 = SecretsStore(secrets_file)
    assert store2.get("ANTHROPIC_API_KEY") == secret_val
    assert store2.list_keys() == ["ANTHROPIC_API_KEY", "TELEGRAM_BOT_TOKEN"]

    raw_bytes = secrets_file.read_bytes()
    if os.name == "nt":
        # On Windows, DPAPI encrypts the file so neither key names nor secret values appear in plaintext
        assert secret_val.encode("utf-8") not in raw_bytes
        assert b"ANTHROPIC_API_KEY" not in raw_bytes

    assert store2.delete("TELEGRAM_BOT_TOKEN") is True
    assert store2.get("TELEGRAM_BOT_TOKEN") is None
    assert store2.delete("NON_EXISTENT") is False


def test_logging_redacts_secrets_and_ui_never_exposes_values(tmp_path: Path) -> None:
    secrets_file = tmp_path / "secrets.bin"
    log_file = tmp_path / "logs" / "app.log"
    store = SecretsStore(secrets_file)
    sensitive = "EAAB-MyTopSecretMetaToken-XYZ12345"
    store.set("META_AD_LIBRARY_TOKEN", sensitive)

    logger = setup_logging(log_file, secrets_store=store)
    logger.info("Connecting with token=%s to Graph API", sensitive)
    for h in logger.handlers:
        h.flush()

    log_content = log_file.read_text(encoding="utf-8")
    assert sensitive not in log_content
    assert "Connecting with token=*** to Graph API" in log_content

    app = create_app(tmp_path, start_worker=False)
    with TestClient(app) as client:
        resp = client.post(
            "/settings/secrets",
            data={
                "name": "GEMINI_API_KEY",
                "value": "AIzaSySecretKeyForTestingRedaction999",
                "action": "set",
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert "AIzaSySecretKeyForTestingRedaction999" not in resp.text
        assert "Đã đặt" in resp.text

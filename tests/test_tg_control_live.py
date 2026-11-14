"""Live Telegram Control Center smoke test (Phase 16). Skips if TELEGRAM_BOT_TOKEN or allowed_chat_ids are absent."""
from __future__ import annotations

import pytest

from videocreator.config import load_settings
from videocreator.paths import get_paths
from videocreator.secrets_store import SecretsStore
from videocreator.telegram_bot import send_text
from videocreator.tg.messages import build_menu_message


@pytest.mark.live
def test_telegram_control_center_menu_live() -> None:
    paths = get_paths()
    secrets = SecretsStore(paths.secrets_file)
    token = secrets.get("TELEGRAM_BOT_TOKEN")
    settings = load_settings(paths.config_file)
    if not token or not settings.telegram.allowed_chat_ids:
        pytest.skip("TELEGRAM_BOT_TOKEN or telegram.allowed_chat_ids not configured")

    text, kb = build_menu_message()
    sent_ids = send_text(paths, text, keyboard=kb)
    assert len(sent_ids) >= 1

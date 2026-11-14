"""Live Telegram bot test (`send_text` and `notify_pending` on sample clip, Phase 06)."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from videocreator.config import load_settings, save_settings
from videocreator.db import get_conn, migrate
from videocreator.paths import get_paths
from videocreator.secrets_store import SecretsStore
from videocreator.telegram_bot import notify_pending_async, send_text_async

SAMPLES_DIR = Path(__file__).resolve().parent / "samples"
CLIP_PORTRAIT = SAMPLES_DIR / "clip1_6s.mp4"


@pytest.mark.live
@pytest.mark.anyio
async def test_telegram_live_send_text_and_video(tmp_path: Path) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id_str = os.environ.get("TELEGRAM_TEST_CHAT_ID")
    if not token or not chat_id_str:
        pytest.skip("TELEGRAM_BOT_TOKEN and TELEGRAM_TEST_CHAT_ID required for live Telegram test")

    paths = get_paths(tmp_path)
    migrate(paths.db_file)
    secrets = SecretsStore(paths.secrets_file)
    secrets.set("TELEGRAM_BOT_TOKEN", token)

    cfg = load_settings(paths.config_file)
    cfg.telegram.allowed_chat_ids = [int(chat_id_str)]
    save_settings(paths.config_file, cfg)

    out_video = paths.media_dir / "output" / "video_1.mp4"
    out_video.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(CLIP_PORTRAIT, out_video)

    with get_conn(paths.db_file) as conn:
        conn.execute(
            """
            INSERT INTO videos (id, status, output_path, duration_s, plan_json)
            VALUES (1, 'pending_approval', 'output/video_1.mp4', 6.0, '{"title":"Test Telegram Live"}')
            """
        )

    msg_ids = await send_text_async(paths, "Test /status live from Video Creator")
    assert len(msg_ids) == 1

    vid_msg_ids = await notify_pending_async(paths, 1)
    assert len(vid_msg_ids) == 1

"""Optional live smoke test against a real `vc-hardened` Muse Gateway (`pytest -m muse_live`)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from videocreator.config import load_settings, save_settings
from videocreator.db import migrate
from videocreator.muse_gateway.client import MuseGatewayClient
from videocreator.muse_gateway.dispatcher import run_muse_dispatcher_tick
from videocreator.muse_gateway.store import create_muse_task, get_muse_task
from videocreator.paths import AppPaths
from videocreator.pipeline.ai_images import generate_ai_image
from videocreator.secrets_store import SecretsStore
from videocreator.tts.muse_engine import synthesize_muse_single
from videocreator.workspaces import create_workspace

pytestmark = pytest.mark.muse_live


def test_muse_live_end_to_end_smoke(tmp_path: Path) -> None:
    live_url = os.environ.get("MUSE_LIVE_GATEWAY_URL", "").strip()
    live_key = os.environ.get("MUSE_LIVE_API_KEY", "").strip()
    if not live_url:
        pytest.skip("Set MUSE_LIVE_GATEWAY_URL (pointing to a vc-hardened gateway) to run live smoke.")

    paths = AppPaths(tmp_path / "live_data")
    paths.ensure_dirs()
    migrate(paths.db_file)
    ws_id = int(create_workspace(paths.db_file, name="Muse Live Smoke", content_policy="full_ai"))

    cfg = load_settings(paths.config_file)
    cfg.muse_gateway.enabled = True
    cfg.muse_gateway.base_url = live_url
    save_settings(paths.config_file, cfg)

    sec = SecretsStore(paths.secrets_file)
    if live_key:
        sec.set("MUSE_GATEWAY_API_KEY", live_key)

    client = MuseGatewayClient(cfg.muse_gateway, sec)
    safety = client.verify_ready_and_safe()
    assert safety["hardened"] is True

    img = generate_ai_image(paths, workspace_id=ws_id, prompt="Minimalist warm studio desk", aspect_ratio="9:16")
    assert img["provider"] == "muse_image"

    track = synthesize_muse_single(
        "Xin chào từ bộ kiểm thử thực tế Muse Gateway.",
        work_dir=tmp_path / "tts_work",
        paths=paths,
    )
    assert track.audio_path.is_file() and track.duration_s > 0.2

    t = create_muse_task(paths.db_file, workspace_id=ws_id, kind="video", prompt="Calm ocean waves at sunrise", params={"duration": 6, "ratio": "9:16"})
    run_muse_dispatcher_tick(paths)
    refreshed = get_muse_task(paths.db_file, int(t["id"]))
    assert refreshed is not None and refreshed["status"] in ("submitted", "succeeded")

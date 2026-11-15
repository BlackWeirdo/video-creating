"""Live API video-generation smoke tests for Kling, Seedance, and Veo (Phase 14).

Requires explicit opt-in via RUN_PAID_VIDEOGEN_LIVE=1 plus API keys to avoid accidental $1-$3 charges.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from videocreator.db import migrate
from videocreator.paths import get_paths
from videocreator.pipeline.broll_generate import generate_broll
from videocreator.pipeline.probe import probe_video
from videocreator.secrets_store import SecretsStore


@pytest.mark.live
def test_kling_gateway_live(tmp_path: Path) -> None:
    if os.environ.get("RUN_PAID_VIDEOGEN_LIVE") != "1":
        pytest.skip("Set RUN_PAID_VIDEOGEN_LIVE=1 to run paid video-generation live test")
    paths = get_paths(tmp_path)
    migrate(paths.db_file)
    secrets = SecretsStore(paths.secrets_file)
    if not (secrets.get("FAL_API_KEY") or os.environ.get("FAL_API_KEY")):
        pytest.skip("FAL_API_KEY not configured")
    if os.environ.get("FAL_API_KEY") and not secrets.get("FAL_API_KEY"):
        secrets.set("FAL_API_KEY", os.environ["FAL_API_KEY"])

    res = generate_broll(
        paths,
        prompt="Warm macro studio lighting on dark volcanic stone surface, vertical 9:16",
        source="kling",
        seconds=5,
        auto_keep=False,
    )
    clip = Path(str(res["preview_path"]))
    assert clip.exists()
    info = probe_video(clip)
    assert info.duration_s >= 3.0

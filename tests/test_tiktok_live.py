"""Live integration test for TikTok inbox/direct publishing (`-m live`, skipped unless TikTok account is connected)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.mark.live
def test_tiktok_live_inbox_upload(tmp_path: Path) -> None:
    if not os.environ.get("TIKTOK_LIVE_TOKEN"):
        pytest.skip("TIKTOK_LIVE_TOKEN not set")

"""Live Meta (Facebook Page & Instagram Reels) publishing test (Phase 07)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from videocreator.posting.meta_auth import list_pages_and_instagram


@pytest.mark.live
def test_meta_live_discover_pages_and_ig(tmp_path: Path) -> None:
    token = os.environ.get("META_TEST_ACCESS_TOKEN")
    if not token:
        pytest.skip("META_TEST_ACCESS_TOKEN not configured for live Meta test")

    discovered = list_pages_and_instagram(token)
    assert isinstance(discovered, list)
    assert len(discovered) >= 1

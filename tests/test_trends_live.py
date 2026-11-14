"""Live integration tests for trend sources (`-m live`, skipped unless API keys are configured)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.mark.live
def test_youtube_trend_source_live(tmp_path: Path) -> None:
    if not os.environ.get("YOUTUBE_API_KEY"):
        pytest.skip("YOUTUBE_API_KEY not set")

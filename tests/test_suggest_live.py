"""Live integration test for trend analysis and suggestion generation (`-m live`)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.mark.live
def test_analyse_and_suggest_live(tmp_path: Path) -> None:
    if not os.environ.get("RUN_LIVE_TREND_SUGGEST"):
        pytest.skip("RUN_LIVE_TREND_SUGGEST not set")

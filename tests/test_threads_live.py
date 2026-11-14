"""Live integration test for Threads publishing (`-m live`, skipped unless Threads account is connected)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.mark.live
def test_threads_live_publish(tmp_path: Path) -> None:
    if not os.environ.get("THREADS_LIVE_TOKEN") or not os.environ.get("THREADS_LIVE_USER_ID"):
        pytest.skip("THREADS_LIVE_TOKEN and THREADS_LIVE_USER_ID not set")

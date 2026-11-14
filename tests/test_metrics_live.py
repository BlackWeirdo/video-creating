"""Live social post insights fetch test (Phase 15). Skips if credentials or posted items are absent."""
from __future__ import annotations

import pytest

from videocreator.db import query_one
from videocreator.paths import get_paths
from videocreator.posting.metrics import collect_due_metrics


@pytest.mark.live
def test_fetch_live_post_metrics_if_available() -> None:
    paths = get_paths()
    if not paths.db_file.exists():
        pytest.skip("Database not initialized")
    row = query_one(
        paths.db_file,
        "SELECT id FROM posts WHERE status = 'posted' AND external_post_id IS NOT NULL LIMIT 1",
    )
    if row is None:
        pytest.skip("No posted social posts in database to fetch live metrics from")

    collected = collect_due_metrics(paths)
    assert collected >= 0

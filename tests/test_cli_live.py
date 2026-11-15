"""Live integration test for `claude_cli` vision shot description and remix plan generation (Phase 04 & 18)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from videocreator.ai.cli_base import find_claude_binary
from videocreator.db import migrate, query_all
from videocreator.paths import get_paths
from videocreator.pipeline.describe import run_describe_footage
from videocreator.pipeline.footage_analyse import run_analyse_footage
from videocreator.pipeline.footage_import import import_footage_file
from videocreator.pipeline.planner import create_remix_plans
from videocreator.products import create_product

SAMPLES_DIR = Path(__file__).resolve().parent / "samples"
CLIP_PORTRAIT = SAMPLES_DIR / "clip1_6s.mp4"


@pytest.mark.live
def test_claude_cli_live_describe_and_plan(tmp_path: Path) -> None:
    if not find_claude_binary():
        pytest.skip("claude CLI binary not installed on host")

    paths = get_paths(tmp_path)
    migrate(paths.db_file)

    pid = create_product(
        paths.db_file,
        name="Nhẫn Bạc Xúc Xắc",
        material="Bạc S925",
        facts={
            "stone": "Không đính đá",
            "craftsmanship": "Chạm khắc thủ công, xử lý oxy hoá",
        },
    )

    fid = import_footage_file(
        paths,
        CLIP_PORTRAIT,
        product_ids=[pid],
        enqueue_analysis=False,
    )
    run_analyse_footage(paths, fid)

    # 1. Live vision shot description via claude_cli
    desc_summary = run_describe_footage(paths, fid)
    assert "Described" in desc_summary

    shots = query_all(
        paths.db_file, "SELECT * FROM shots WHERE footage_id = ? ORDER BY idx ASC", (fid,)
    )
    assert len(shots) >= 1
    for s in shots:
        assert len(str(s["description"]).strip()) > 5
        tags = json.loads(s["tags_json"])
        assert isinstance(tags, list) and len(tags) >= 1

    # 2. Live remix plan generation + fact-checker via claude_cli
    video_ids = create_remix_plans(
        paths,
        fid,
        count=1,
        voice_lang="vi",
        caption_lang="vi",
        target_duration_s=6.0,
    )
    assert len(video_ids) == 1

    videos = query_all(paths.db_file, "SELECT * FROM videos WHERE id = ?", (video_ids[0],))
    assert len(videos) == 1
    assert videos[0]["status"] == "planned"
    plan = json.loads(videos[0]["plan_json"])
    assert len(plan["shots"]) >= 1
    assert set(plan["captions"].keys()) == {"facebook", "instagram", "threads", "tiktok"}

    # 3. Verify ai_usage recorded subscription route with cost_usd == 0.0
    usage_rows = query_all(paths.db_file, "SELECT * FROM ai_usage")
    assert len(usage_rows) >= 2
    for u in usage_rows:
        assert u["route"] == "subscription"
        assert float(u["cost_usd"]) == 0.0

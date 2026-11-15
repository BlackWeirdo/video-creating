"""Local SQLite + real FFmpeg tests for Manual Tickets, B-roll planner rules, budget cap, and mixed render (Phase 14)."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from videocreator.ai.base import BudgetExceeded
from videocreator.config import load_settings, save_settings
from videocreator.db import get_conn, migrate, query_one
from videocreator.manual.fulfill import fulfill_manual_ticket
from videocreator.manual.tickets import create_manual_ticket, expire_stale_tickets
from videocreator.paths import get_paths
from videocreator.pipeline.broll_generate import generate_broll
from videocreator.pipeline.plan_schema import PlannedShot, PlatformCaption, PlatformCaptions, VideoPlanItem
from videocreator.pipeline.plan_validate import validate_and_normalize_plan
from videocreator.pipeline.probe import probe_video
from videocreator.pipeline.render import render_video

SAMPLE_CLIP_1 = Path(__file__).parent / "samples" / "clip1_6s.mp4"
SAMPLE_CLIP_2 = Path(__file__).parent / "samples" / "clip2_6s.mp4"


def _dummy_captions() -> PlatformCaptions:
    c = PlatformCaption(text="Chế tác bạc thủ công S925", hashtags=["#bac925"])
    return PlatformCaptions(facebook=c, instagram=c, threads=c, tiktok=c)


@pytest.mark.local
def test_manual_ticket_roundtrip_and_invalid_file_rejection(tmp_path: Path) -> None:
    paths = get_paths(tmp_path)
    migrate(paths.db_file)

    tid = create_manual_ticket(
        paths,
        prompt="Khói mỏng trên mặt bàn gỗ nghệ nhân kim hoàn",
        seconds=6,
    )
    assert tid >= 1

    # 1. Invalid file extension / corrupt file is rejected
    bad_file = tmp_path / "not_a_video.txt"
    bad_file.write_text("not a video", encoding="utf-8")
    with pytest.raises(ValueError):
        fulfill_manual_ticket(paths, tid, bad_file)

    fake_mp4 = tmp_path / "corrupt.mp4"
    fake_mp4.write_bytes(b"not valid mp4 bytes")
    with pytest.raises(ValueError):
        fulfill_manual_ticket(paths, tid, fake_mp4)

    # 2. Valid sample video fulfills ticket -> creates asset + ai_broll shot with has_product=0
    asset_id, shot_id = fulfill_manual_ticket(paths, tid, SAMPLE_CLIP_2)
    assert asset_id >= 1
    assert shot_id >= 1

    t_row = query_one(paths.db_file, "SELECT * FROM manual_tickets WHERE id = ?", (tid,))
    assert t_row is not None
    assert t_row["status"] == "closed"
    assert int(t_row["result_asset_id"]) == asset_id

    s_row = query_one(paths.db_file, "SELECT * FROM shots WHERE id = ?", (shot_id,))
    assert s_row is not None
    assert s_row["footage_id"] is None
    assert int(s_row["asset_id"]) == asset_id
    assert int(s_row["has_product"]) == 0
    assert "ai_broll" in str(s_row["tags_json"])


@pytest.mark.local
def test_planner_broll_rules_and_mixed_footage_broll_render(tmp_path: Path) -> None:
    paths = get_paths(tmp_path)
    migrate(paths.db_file)

    rel_ftg = "footage/real_clip.mp4"
    abs_ftg = paths.media_dir / rel_ftg
    abs_ftg.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SAMPLE_CLIP_1, abs_ftg)

    with get_conn(paths.db_file) as conn:
        conn.execute(
            """
            INSERT INTO footage (id, path, sha256, duration_s, width, height, orientation, status)
            VALUES (1, ?, 'sha_real_1', 6.0, 1080, 1920, 'portrait', 'analysed')
            """,
            (rel_ftg,),
        )
        # Real footage product shot (#1) and real footage process shot (#2)
        conn.execute(
            """
            INSERT INTO shots (id, footage_id, idx, start_s, end_s, description, tags_json, has_product, quality)
            VALUES
              (1, 1, 1, 0.0, 3.0, 'Cận cảnh nhẫn bạc thật', '["product","closeup"]', 1, 5),
              (2, 1, 2, 3.0, 6.0, 'Đánh bóng nhẫn bạc thật', '["process"]', 1, 5)
            """
        )

    # Fulfill 3 manual B-roll shots (#3, #4, #5)
    broll_shot_ids: list[int] = []
    for i in range(3):
        tid = create_manual_ticket(paths, prompt=f"Cảnh phụ #{i+1}", seconds=5)
        _aid, sid = fulfill_manual_ticket(paths, tid, SAMPLE_CLIP_2)
        broll_shot_ids.append(sid)

    shots_by_id = {
        int(r["id"]): r
        for r in [
            query_one(paths.db_file, "SELECT * FROM shots WHERE id = ?", (sid,))
            for sid in [1, 2, *broll_shot_ids]
        ]
        if r is not None
    }

    # Rule 1: Rejects B-roll at hook index 0 (BR-PRD-08)
    plan_hook_broll = VideoPlanItem(
        title="B-roll ở hook",
        formula="hook-first",
        shots=[
            PlannedShot(shot_id=broll_shot_ids[0], start_s=0.0, duration_s=3.0, text="Mở đầu"),
            PlannedShot(shot_id=1, start_s=0.0, duration_s=3.0, text="Sản phẩm thật"),
            PlannedShot(shot_id=2, start_s=3.0, duration_s=3.0, text="Hoàn thiện"),
        ],
        captions=_dummy_captions(),
    )
    with pytest.raises(ValueError, match="hook"):
        validate_and_normalize_plan(
            plan_hook_broll,
            shot_map=shots_by_id,
            product_map={},
            voice_lang="none",
            caption_lang="vi",
            target_duration_s=9.0,
        )

    # Rule 2: Rejects > 2 B-roll shots in a single video (BR-PRD-08)
    plan_3_broll = VideoPlanItem(
        title="Quá 2 cảnh phụ",
        formula="process-story",
        shots=[
            PlannedShot(shot_id=1, start_s=0.0, duration_s=2.5, text="Nhẫn bạc thật"),
            PlannedShot(shot_id=broll_shot_ids[0], start_s=0.0, duration_s=2.0, text="Cảnh phụ 1"),
            PlannedShot(shot_id=broll_shot_ids[1], start_s=0.0, duration_s=2.0, text="Cảnh phụ 2"),
            PlannedShot(shot_id=broll_shot_ids[2], start_s=0.0, duration_s=2.0, text="Cảnh phụ 3"),
        ],
        captions=_dummy_captions(),
    )
    with pytest.raises(ValueError, match="maximum allowed is 2"):
        validate_and_normalize_plan(
            plan_3_broll,
            shot_map=shots_by_id,
            product_map={},
            voice_lang="none",
            caption_lang="vi",
            target_duration_s=9.0,
        )

    # Valid mixed plan: Real product shot #1 at hook -> B-roll shot -> Real shot #2
    valid_mixed_plan = VideoPlanItem(
        title="Phối cảnh thật và cảnh phụ",
        formula="hook-first",
        shots=[
            PlannedShot(shot_id=1, start_s=0.0, duration_s=2.5, text="Chế tác bạc S925"),
            PlannedShot(shot_id=broll_shot_ids[0], start_s=0.0, duration_s=2.0, text="Không gian xưởng"),
            PlannedShot(shot_id=2, start_s=3.0, duration_s=2.5, text="Hoàn thiện thủ công"),
        ],
        captions=_dummy_captions(),
    )
    normalized = validate_and_normalize_plan(
        valid_mixed_plan,
        shot_map=shots_by_id,
        product_map={},
        voice_lang="none",
        caption_lang="vi",
        target_duration_s=7.0,
    )

    # Render the mixed plan with real FFmpeg and verify master MP4
    with get_conn(paths.db_file) as conn:
        v_cur = conn.execute(
            """
            INSERT INTO videos (status, plan_json, captions_json)
            VALUES ('planned', ?, '{}')
            """,
            (json.dumps(normalized, ensure_ascii=False),),
        )
        vid = int(v_cur.lastrowid or 0)

    render_video(paths, vid)
    v_row = query_one(paths.db_file, "SELECT * FROM videos WHERE id = ?", (vid,))
    assert v_row is not None
    assert v_row["status"] == "pending_approval"
    master_file = paths.media_dir / str(v_row["output_path"])
    assert master_file.exists()
    info = probe_video(master_file)
    assert info.width == 1080
    assert info.height == 1920
    assert 6.5 <= info.duration_s <= 7.6


@pytest.mark.local
def test_generative_daily_budget_blocks_before_api_call(tmp_path: Path) -> None:
    paths = get_paths(tmp_path)
    migrate(paths.db_file)

    cfg = load_settings(paths.config_file)
    cfg.budget.generative_daily_usd = 0.50  # $0.50 daily generative ceiling
    save_settings(paths.config_file, cfg)

    # 6s of kling ($0.14/s = $0.84) exceeds $0.50 ceiling -> blocked before API call
    with pytest.raises(BudgetExceeded):
        generate_broll(
            paths,
            prompt="Khói mỏng nghệ thuật",
            source="kling",
            seconds=6,
        )


@pytest.mark.local
def test_manual_ticket_48h_remind_then_cancel(tmp_path: Path) -> None:
    from datetime import datetime, timedelta, timezone

    paths = get_paths(tmp_path)
    migrate(paths.db_file)

    t0 = datetime(2026, 11, 10, 10, 0, 0, tzinfo=timezone.utc)
    t0_iso = t0.strftime("%Y-%m-%dT%H:%M:%SZ")

    tid1 = create_manual_ticket(paths, prompt="Cảnh phụ nhắc rồi nạp", seconds=6)
    tid2 = create_manual_ticket(paths, prompt="Cảnh phụ nhắc rồi huỷ", seconds=6)
    with get_conn(paths.db_file) as conn:
        conn.execute("UPDATE manual_tickets SET created_at = ? WHERE id IN (?, ?)", (t0_iso, tid1, tid2))

    # 1st check after 49h: open -> reminded (not yet cancelled)
    cancelled_1 = expire_stale_tickets(paths, now_dt=t0 + timedelta(hours=49))
    assert cancelled_1 == []
    r1 = query_one(paths.db_file, "SELECT status FROM manual_tickets WHERE id = ?", (tid1,))
    r2 = query_one(paths.db_file, "SELECT status FROM manual_tickets WHERE id = ?", (tid2,))
    assert r1 is not None and r1["status"] == "reminded"
    assert r2 is not None and r2["status"] == "reminded"

    # A reminded ticket (#tid1) can still be fulfilled
    aid, sid = fulfill_manual_ticket(paths, tid1, SAMPLE_CLIP_2)
    assert aid >= 1 and sid >= 1

    # 2nd check after 50h: remaining reminded ticket (#tid2) is cancelled
    cancelled_2 = expire_stale_tickets(paths, now_dt=t0 + timedelta(hours=50))
    assert cancelled_2 == [tid2]
    r2_after = query_one(paths.db_file, "SELECT status FROM manual_tickets WHERE id = ?", (tid2,))
    assert r2_after is not None and r2_after["status"] == "cancelled"

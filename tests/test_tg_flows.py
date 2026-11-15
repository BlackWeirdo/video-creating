"""Local SQLite-backed tests for Telegram callbacks, commands, redo/auto-retry limits, and pending input (Phase 16)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from videocreator.config import load_settings, save_settings
from videocreator.db import get_conn, migrate, query_all, query_one
from videocreator.paths import AppPaths, get_paths
from videocreator.pipeline.quality_score import score_rendered_video
from videocreator.posting.publish import publish_due_posts
from videocreator.presets import create_preset, export_presets_json, import_presets_json, list_presets
from videocreator.tg.callbacks import route_callback
from videocreator.tg.commands import execute_command
from videocreator.tg.pending_input import handle_pending_reply_input


def _make_tg_paths(tmp_path: Path) -> AppPaths:
    paths = get_paths(tmp_path)
    migrate(paths.db_file)
    cfg = load_settings(paths.config_file)
    cfg.telegram.allowed_chat_ids = [-100999888]
    cfg.telegram.approver_user_ids = [101, 102]
    save_settings(paths.config_file, cfg)
    return paths


@pytest.mark.local
def test_allowlist_and_round1_suggestion_idempotency(tmp_path: Path) -> None:
    paths = _make_tg_paths(tmp_path)

    with get_conn(paths.db_file) as conn:
        t_cur = conn.execute(
            """
            INSERT INTO trend_items (source, external_id, url, author, caption, published_at, score, analysis_json)
            VALUES ('youtube', 'yt_tg_1', 'https://youtube.com/watch?v=1', 'Brand', 'Cap', '2026-11-12T10:00:00Z', 50.0, '{"hook":"h"}')
            """
        )
        tid = int(t_cur.lastrowid or 0)
        s_cur = conn.execute(
            """
            INSERT INTO suggestions (trend_item_id, text, formula_json, status)
            VALUES (?, 'Ý tưởng thử nghiệm', '{"formula":"hook-first"}', 'sent')
            """,
            (tid,),
        )
        sid = int(s_cur.lastrowid or 0)

    # 1. Unauthorized chat rejected
    allowed_c, msg_c, won_c, _ = route_callback(
        paths, chat_id=-100111222, user_id=101, user_name="Minh", data=f"sg_ok:{sid}:1"
    )
    assert allowed_c is False
    assert won_c is False

    # 2. Non-approver user rejected
    allowed_u, msg_u, won_u, _ = route_callback(
        paths, chat_id=-100999888, user_id=999, user_name="Guest", data=f"sg_ok:{sid}:1"
    )
    assert allowed_u is False
    assert won_u is False

    # 3. Approver clicks sg_ok:<sid>:1 -> accepted + 1 plan job enqueued
    allowed_1, msg_1, won_1, _ = route_callback(
        paths, chat_id=-100999888, user_id=101, user_name="Minh", data=f"sg_ok:{sid}:1"
    )
    assert allowed_1 is True
    assert won_1 is True
    assert "Minh" in msg_1

    # 4. Second click on same suggestion does not enqueue a second job
    allowed_2, msg_2, won_2, _ = route_callback(
        paths, chat_id=-100999888, user_id=102, user_name="Lan", data=f"sg_ok:{sid}:1"
    )
    assert allowed_2 is True
    assert won_2 is False
    assert "đã được xử lý rồi" in msg_2

    jobs = query_all(paths.db_file, "SELECT * FROM jobs WHERE kind = 'plan'")
    assert len(jobs) == 1


@pytest.mark.local
def test_redo_limit_and_separate_auto_retry_counter(tmp_path: Path) -> None:
    paths = _make_tg_paths(tmp_path)

    with get_conn(paths.db_file) as conn:
        cur = conn.execute(
            """
            INSERT INTO videos (status, plan_json, captions_json)
            VALUES ('rendered', '{"title":"V1","formula":"hook-first","shots":[]}', '{}')
            """
        )
        v1 = int(cur.lastrowid or 0)

    # Auto-quality score < 8.0 triggers auto_retry_count = 1 (does not touch redo_count)
    st1, v2, sc1 = score_rendered_video(paths, v1, score_override=6.5, notes_override="Mở đầu hơi chậm")
    assert st1 == "superseded"
    assert v2 != v1
    assert sc1 == 6.5

    row_v1 = query_one(paths.db_file, "SELECT status FROM videos WHERE id = ?", (v1,))
    row_v2 = query_one(paths.db_file, "SELECT * FROM videos WHERE id = ?", (v2,))
    assert row_v1 is not None and row_v1["status"] == "superseded"
    assert row_v2 is not None
    assert int(row_v2["auto_retry_count"]) == 1
    assert int(row_v2["redo_count"]) == 0

    # Mark v2 rendered and score high -> transitions to pending_approval
    with get_conn(paths.db_file) as conn:
        conn.execute("UPDATE videos SET status = 'rendered' WHERE id = ?", (v2,))
    st2, v2_active, sc2 = score_rendered_video(paths, v2, score_override=8.8, notes_override="Rõ sản phẩm")
    assert st2 == "pending_approval"
    assert v2_active == v2

    # Human approver clicks Làm lại #1 -> allowed (redo_count = 1)
    ok_r1, _msg_r1, won_r1, _ = route_callback(
        paths, chat_id=-100999888, user_id=101, user_name="Minh", data=f"redo:{v2}"
    )
    assert ok_r1 is True and won_r1 is True
    v3_row = query_one(paths.db_file, "SELECT * FROM videos WHERE supersedes_id = ?", (v2,))
    assert v3_row is not None
    v3 = int(v3_row["id"])
    assert int(v3_row["redo_count"]) == 1

    # Human approver clicks Làm lại #2 -> allowed (redo_count = 2)
    with get_conn(paths.db_file) as conn:
        conn.execute("UPDATE videos SET status = 'pending_approval' WHERE id = ?", (v3,))
    ok_r2, _msg_r2, won_r2, _ = route_callback(
        paths, chat_id=-100999888, user_id=101, user_name="Minh", data=f"redo:{v3}"
    )
    assert ok_r2 is True and won_r2 is True
    v4_row = query_one(paths.db_file, "SELECT * FROM videos WHERE supersedes_id = ?", (v3,))
    assert v4_row is not None
    v4 = int(v4_row["id"])
    assert int(v4_row["redo_count"]) == 2

    # Human approver clicks Làm lại #3 -> blocked (max 2 human redos)
    with get_conn(paths.db_file) as conn:
        conn.execute("UPDATE videos SET status = 'pending_approval' WHERE id = ?", (v4,))
    ok_r3, msg_r3, won_r3, _ = route_callback(
        paths, chat_id=-100999888, user_id=101, user_name="Minh", data=f"redo:{v4}"
    )
    assert ok_r3 is True
    assert won_r3 is False
    assert "tối đa 2 lần" in msg_r3


@pytest.mark.local
def test_pause_command_blocks_auto_publishing_and_pending_reply_inputs(tmp_path: Path) -> None:
    paths = _make_tg_paths(tmp_path)
    now_dt = datetime(2026, 11, 13, 10, 0, tzinfo=timezone.utc)

    with get_conn(paths.db_file) as conn:
        conn.execute(
            """
            INSERT INTO accounts (id, platform, external_id, name, lang, secret_key, enabled)
            VALUES (1, 'facebook', 'p1', 'FB Page', 'vi', 'META_PAGE_1', 1)
            """
        )
        conn.execute(
            """
            INSERT INTO videos (id, status, captions_json)
            VALUES (50, 'pending_approval', '{"threads":{"text":"Old"}}')
            """
        )
        conn.execute(
            """
            INSERT INTO posts (id, video_id, account_id, status, scheduled_at)
            VALUES (1, 50, 1, 'scheduled', '2026-11-13T09:55:00Z')
            """
        )

    # /pause command stops publish_due_posts from publishing
    ok_p, msg_p, _ = execute_command(
        paths, chat_id=-100999888, user_id=101, user_name="Minh", command="pause", now_dt=now_dt
    )
    assert ok_p is True
    assert "tạm dừng" in msg_p.lower()
    assert publish_due_posts(paths, now_dt=now_dt) == 0

    # Caption edit via reply (truncates Threads caption to 500 chars)
    route_callback(
        paths,
        chat_id=-100999888,
        user_id=101,
        user_name="Minh",
        data="cap_plat:50:threads",
        now_dt=now_dt,
    )
    long_caption = "Nhẫn bạc S925 " * 60  # > 500 chars
    handled_cap, cap_msg = handle_pending_reply_input(
        paths,
        chat_id=-100999888,
        user_id=101,
        user_name="Minh",
        text=long_caption,
        now_dt=now_dt + timedelta(minutes=2),
    )
    assert handled_cap is True
    assert cap_msg is not None and "500 ký tự" in cap_msg
    v_row = query_one(paths.db_file, "SELECT captions_json FROM videos WHERE id = 50")
    assert v_row is not None
    saved_caps = json.loads(str(v_row["captions_json"]))
    assert len(saved_caps["threads"]["text"]) == 500

    # Reject reason via reply after 10-minute TTL expires -> rejected as expired
    route_callback(
        paths,
        chat_id=-100999888,
        user_id=101,
        user_name="Minh",
        data="no_ask:50",
        now_dt=now_dt,
    )
    handled_exp, exp_msg = handle_pending_reply_input(
        paths,
        chat_id=-100999888,
        user_id=101,
        user_name="Minh",
        text="Hình hơi tối",
        now_dt=now_dt + timedelta(minutes=15),
    )
    assert handled_exp is False
    assert exp_msg is not None and "hết hạn" in exp_msg

    # Presets JSON export/import roundtrip
    create_preset(paths.db_file, name="Ra mắt bộ sưu tập", kind="writer", body="Giọng sang trọng, nhấn mạnh chế tác tay")
    raw_json = export_presets_json(paths.db_file)
    assert "Ra mắt bộ sưu tập" in raw_json
    imported = import_presets_json(paths.db_file, raw_json)
    assert imported == 1
    assert len(list_presets(paths.db_file)) == 1

    # Verify create_app registers 'replan' handler on job_registry
    from videocreator.app import create_app
    from videocreator.jobs import default_registry

    create_app(data_dir=tmp_path, start_worker=False)
    assert default_registry.get("replan") is not None

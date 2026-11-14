"""Real SQLite and FastAPI tests for approval queue, atomic approve/reject, and 2-layer Telegram allowlist (Phase 06)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from videocreator.api.routes_products import create_product
from videocreator.app import create_app
from videocreator.approvals import approve, reject
from videocreator.config import load_settings, save_settings
from videocreator.db import get_conn, migrate, query_one
from videocreator.paths import get_paths
from videocreator.state import InvalidTransitionError
from videocreator.telegram_bot import build_status_text, process_approval_callback


@pytest.mark.local
def test_approve_reject_and_no_planned_to_approved_shortcut(tmp_path: Path) -> None:
    db_file = tmp_path / "videocreator.db"
    migrate(db_file)

    with get_conn(db_file) as conn:
        conn.execute(
            """
            INSERT INTO videos (id, status, plan_json)
            VALUES
                (1, 'planned', '{}'),
                (2, 'pending_approval', '{}'),
                (3, 'pending_approval', '{}')
            """
        )

    # Cannot jump directly from planned -> approved
    with pytest.raises(InvalidTransitionError):
        approve(db_file, 1, by="ui")

    # Video #2: first approve wins, second approve or reject returns False ("already processed")
    assert approve(db_file, 2, by="ui", target_account_ids=[10, 20]) is True
    assert approve(db_file, 2, by="tg:999:Other") is False
    assert reject(db_file, 2, by="tg:999:Other", reason="Too late") is False

    v2 = query_one(db_file, "SELECT status, approved_by, target_accounts_json FROM videos WHERE id = 2")
    assert v2 is not None
    assert v2["status"] == "approved"
    assert v2["approved_by"] == "ui"
    assert json.loads(v2["target_accounts_json"]) == [10, 20]

    # Video #3: first reject wins, subsequent approve returns False
    assert reject(db_file, 3, by="ui", reason="Chưa nét") is True
    assert approve(db_file, 3, by="ui") is False

    v3 = query_one(db_file, "SELECT status, reject_reason FROM videos WHERE id = 3")
    assert v3 is not None
    assert v3["status"] == "rejected"
    assert v3["reject_reason"] == "Chưa nét"


@pytest.mark.local
def test_telegram_two_layer_allowlist_and_concurrent_callback(tmp_path: Path) -> None:
    paths = get_paths(tmp_path)
    migrate(paths.db_file)

    cfg = load_settings(paths.config_file)
    cfg.telegram.allowed_chat_ids = [-100123456]
    cfg.telegram.approver_user_ids = [1001, 1002]
    save_settings(paths.config_file, cfg)

    with get_conn(paths.db_file) as conn:
        conn.execute(
            "INSERT INTO videos (id, status, plan_json) VALUES (10, 'pending_approval', '{}')"
        )

    # 1. Unauthorized chat -> blocked
    allowed1, msg1, won1 = process_approval_callback(
        paths.db_file,
        paths.config_file,
        chat_id=-999999,
        user_id=1001,
        user_name="Minh",
        data="ok:10",
    )
    assert allowed1 is False
    assert won1 is False

    # 2. Authorized chat, but user_id not in approver_user_ids -> blocked
    allowed2, msg2, won2 = process_approval_callback(
        paths.db_file,
        paths.config_file,
        chat_id=-100123456,
        user_id=7777,
        user_name="Stranger",
        data="ok:10",
    )
    assert allowed2 is False
    assert won2 is False

    # 3. Authorized chat + authorized approver 1001 -> wins approval
    allowed3, msg3, won3 = process_approval_callback(
        paths.db_file,
        paths.config_file,
        chat_id=-100123456,
        user_id=1001,
        user_name="Minh",
        data="ok:10",
    )
    assert allowed3 is True
    assert won3 is True
    assert "Đã duyệt bởi Minh" in msg3

    # 4. Second approver 1002 clicks Reject a moment later -> receives "đã được xử lý rồi"
    allowed4, msg4, won4 = process_approval_callback(
        paths.db_file,
        paths.config_file,
        chat_id=-100123456,
        user_id=1002,
        user_name="Lan",
        data="no:10",
    )
    assert allowed4 is True
    assert won4 is False
    assert "đã được xử lý rồi" in msg4

    status_text = build_status_text(paths.db_file, paths.config_file)
    assert "Đã duyệt: 1" in status_text


@pytest.mark.local
def test_approval_web_ui_shows_warnings_ai_broll_badge_and_edits_captions(tmp_path: Path) -> None:
    app = create_app(data_dir=tmp_path, start_worker=False)
    paths = app.state.paths

    pid = create_product(
        paths.db_file,
        name="Nhẫn Bạc Xúc Xắc",
        material="Bạc S925",
        facts={"stone": "Không đính đá"},
    )
    with get_conn(paths.db_file) as conn:
        conn.execute(
            "INSERT INTO assets (id, kind, path, duration_s, meta_json) VALUES (5, 'broll', 'assets/broll_5.mp4', 4.0, '{\"source\":\"ai_broll\"}')"
        )
        conn.execute(
            "INSERT INTO shots (id, asset_id, idx, start_s, end_s, has_product) VALUES (50, 5, 1, 0.0, 4.0, 0)"
        )
        plan = {
            "formula": "hook-first",
            "title": "Video Chờ Duyệt Mẫu",
            "shots": [{"shot_id": 50, "start_s": 0.0, "duration_s": 4.0, "text": "Cảnh xưởng"}],
            "captions": {
                "facebook": {"text": "FB gốc", "hashtags": ["#bac"]},
                "instagram": {"text": "IG gốc", "hashtags": ["#bac"]},
                "threads": {"text": "TH gốc", "hashtags": ["#bac"]},
                "tiktok": {"text": "TT gốc", "hashtags": ["#bac"]},
            },
            "unverified_claims": ["Bạc S999 đính kim cương"],
        }
        conn.execute(
            """
            INSERT INTO videos (
                id, product_ids_json, engine, status, plan_json,
                output_path, duration_s, preflight_json, unsupported_claims_json,
                quality_score, quality_notes
            )
            VALUES (1, ?, 'studio', 'pending_approval', ?, 'output/video_1.mp4', 12.0, ?, ?, 8.9, 'Ánh sáng tốt')
            """,
            (
                f"[{pid}]",
                json.dumps(plan, ensure_ascii=False),
                json.dumps({"tiktok": ["Không đăng được tiktok: dài quá 90.0s"]}),
                json.dumps(["Bạc S999 đính kim cương"]),
            ),
        )

    with TestClient(app) as client:
        page = client.get("/approval")
        assert page.status_code == 200
        assert "Nhẫn Bạc Xúc Xắc" in page.text
        assert "Có cảnh AI B-roll" in page.text
        assert "Có hiệu ứng chuyển động trên footage (Studio)" in page.text
        assert "8.9/10" in page.text
        assert "Ánh sáng tốt" in page.text
        assert "Bạc S999 đính kim cương" in page.text
        assert "Không đăng được tiktok" in page.text

        resp = client.post(
            "/videos/1/approve",
            data={
                "caption_facebook_text": "FB đã chỉnh sửa lúc duyệt",
                "caption_facebook_hashtags": "#bac925 #thucong",
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert "Đã duyệt video" in resp.text

    v_after = query_one(paths.db_file, "SELECT status, captions_json FROM videos WHERE id = 1")
    assert v_after is not None
    assert v_after["status"] == "approved"
    caps = json.loads(v_after["captions_json"])
    assert caps["facebook"]["text"] == "FB đã chỉnh sửa lúc duyệt"

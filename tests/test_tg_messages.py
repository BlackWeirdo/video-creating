"""Local unit tests for pure Telegram message & keyboard builders (Phase 16)."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from videocreator.config import Settings
from videocreator.tg.messages import (
    build_account_toggle_keyboard,
    build_approval_message,
    build_new_footage_message,
    build_post_now_confirm_keyboard,
    build_trend_suggestion_message,
)
from videocreator.tg.quiet_hours import is_quiet_hours
from videocreator.tg.status_messages import build_menu_message


def _assert_all_callbacks_under_64_bytes(kb: list[list[tuple[str, str]]]) -> None:
    for row in kb:
        for label, cb_data in row:
            assert label
            assert len(cb_data.encode("utf-8")) <= 64, f"Callback data too long: {cb_data}"


@pytest.mark.local
def test_trend_suggestion_message_normal_and_missing_shots() -> None:
    sugg_ok = {
        "id": 12,
        "text": "Mở đầu bằng cận cảnh đánh bóng nhẫn bạc S925",
        "formula_json": json.dumps({"formula": "process-story", "missing_shots": ""}),
    }
    trend = {
        "source": "youtube",
        "author": "Silver Craft Studio",
        "url": "https://www.youtube.com/watch?v=abc123xyz",
        "metrics_json": json.dumps({"views": 85000, "likes": 4200, "comments": 190}),
        "analysis_json": json.dumps({"why_it_works": "Nhịp cắt 1.5s giữ chân người xem"}),
    }
    text, kb = build_trend_suggestion_message(sugg_ok, trend)
    assert "Silver Craft Studio" in text
    assert "process-story" in text
    assert len(kb) == 1
    assert [b[1] for b in kb[0]] == ["sg_ok:12:1", "sg_ok:12:3", "sg_no:12"]
    _assert_all_callbacks_under_64_bytes(kb)

    sugg_missing = {
        "id": 13,
        "text": "Video đeo thử ngoài nắng",
        "formula_json": json.dumps(
            {"formula": "hook-first", "missing_shots": "cảnh đeo nhẫn ngoài nắng tự nhiên"}
        ),
    }
    text_m, kb_m = build_trend_suggestion_message(sugg_missing, trend)
    assert "cần quay thêm" in text_m.lower()
    # Must omit create buttons when missing required shots (FR-TG-10)
    assert [b[1] for b in kb_m[0]] == ["sg_no:13"]
    _assert_all_callbacks_under_64_bytes(kb_m)


@pytest.mark.local
def test_new_footage_and_approval_6_button_keyboard() -> None:
    ftg_text, ftg_kb = build_new_footage_message(7, "ring_polishing.mp4", 9)
    assert "ring_polishing.mp4" in ftg_text
    assert "9 shot" in ftg_text
    assert [b[1] for b in ftg_kb[0]] == ["ftg_ok:7:3", "ftg_ok:7:5", "ftg_no:7"]
    _assert_all_callbacks_under_64_bytes(ftg_kb)

    video_item = {
        "id": 42,
        "title": "Nhẫn bạc S925 thủ công",
        "formula": "hook-first",
        "duration_s": 18.5,
        "product_names": ["Nhẫn bạc Xoắn"],
        "quality_score": 8.7,
        "quality_notes": "Mở đầu rõ sản phẩm",
        "has_ai_broll": True,
        "unverified_claims": ["Bảo hành trọn đời"],
        "preflight": {"instagram": []},
        "captions": {"facebook": {"text": "Chế tác thủ công từng đường nét"}},
    }
    cap, kb = build_approval_message(
        video_item,
        account_names=["FB Chính", "IG Chính"],
        next_slot_str="14/11 19:00",
    )
    assert "8.7/10" in cap
    assert "AI B-roll" in cap
    assert "Bảo hành trọn đời" in cap
    flat_codes = [b[1] for row in kb for b in row]
    assert flat_codes == [
        "ok:42",
        "now_ask:42",
        "no_ask:42",
        "redo:42",
        "acc_menu:42",
        "cap_menu:42",
    ]
    _assert_all_callbacks_under_64_bytes(kb)
    _assert_all_callbacks_under_64_bytes(build_post_now_confirm_keyboard(42))
    _assert_all_callbacks_under_64_bytes(
        build_account_toggle_keyboard(
            42,
            [{"id": 1, "platform": "facebook", "name": "Page A"}, {"id": 2, "platform": "instagram", "name": "IG A"}],
            {1},
        )
    )
    _menu_txt, menu_kb = build_menu_message()
    _assert_all_callbacks_under_64_bytes(menu_kb)


@pytest.mark.local
def test_quiet_hours_window() -> None:
    cfg = Settings()
    cfg.schedule.timezone = "Asia/Ho_Chi_Minh"
    cfg.telegram.quiet_hours = "22:00-07:00"

    # 16:00 UTC = 23:00 ICT -> inside quiet hours
    assert is_quiet_hours(cfg, datetime(2026, 11, 13, 16, 0, tzinfo=timezone.utc)) is True
    # 04:00 UTC = 11:00 ICT -> outside quiet hours
    assert is_quiet_hours(cfg, datetime(2026, 11, 13, 4, 0, tzinfo=timezone.utc)) is False

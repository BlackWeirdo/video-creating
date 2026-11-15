"""Real SQLite tests for daily report, token expiry alerts, nightly backup, and disk retention cleanup (Phase 10)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from videocreator.app import create_app
from videocreator.config import load_settings, save_settings
from videocreator.db import get_conn, query_one
from videocreator.maintenance import (
    LOW_DISK_THRESHOLD_BYTES,
    check_expiring_tokens,
    run_nightly_backup_and_cleanup,
)
from videocreator.posting.accounts import upsert_account
from videocreator.reports import daily_summary


@pytest.mark.local
def test_daily_report_counts_and_token_expiry_alerts(tmp_path: Path) -> None:
    app = create_app(data_dir=tmp_path, start_worker=False)
    paths = app.state.paths

    tz_ict = ZoneInfo("Asia/Ho_Chi_Minh")
    now_local = datetime(2026, 11, 14, 21, 30, 0, tzinfo=tz_ict)
    now_utc = now_local.astimezone(timezone.utc)

    # 1 account expiring in 3 days (< 7 days -> alert), 1 account expiring in 20 days (ok)
    exp_soon = (now_utc + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    exp_later = (now_utc + timedelta(days=20)).strftime("%Y-%m-%dT%H:%M:%SZ")

    acc1 = upsert_account(
        paths,
        platform="facebook",
        external_id="fb_exp_1",
        name="FB Sắp Hết Hạn",
        access_token="tok_exp_secret_111",
        token_expires_at=exp_soon,
    )
    acc2 = upsert_account(
        paths,
        platform="instagram",
        external_id="ig_ok_2",
        name="IG Còn Hạn Dài",
        access_token="tok_exp_secret_222",
        token_expires_at=exp_later,
    )

    expiring = check_expiring_tokens(paths, now_dt=now_utc)
    assert len(expiring) == 1
    assert expiring[0]["id"] == acc1
    assert expiring[0]["name"] == "FB Sắp Hết Hạn"

    # Populate videos, posts, and AI usage for daily_summary
    posted_at_iso = (now_utc - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    tomorrow_slot_iso = (now_utc + timedelta(hours=14)).strftime("%Y-%m-%dT%H:%M:%SZ")
    over_2d_iso = (now_utc + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    day_str = now_utc.strftime("%Y-%m-%d")

    with get_conn(paths.db_file) as conn:
        conn.execute(
            """
            INSERT INTO videos (id, status) VALUES
                (1, 'posted'),
                (2, 'failed'),
                (3, 'pending_approval'),
                (4, 'pending_approval'),
                (5, 'scheduled'),
                (6, 'scheduled')
            """
        )
        conn.execute(
            """
            INSERT INTO posts (video_id, account_id, status, scheduled_at, posted_at)
            VALUES
                (1, ?, 'posted', ?, ?),
                (2, ?, 'failed', ?, NULL),
                (5, ?, 'scheduled', ?, NULL),
                (6, ?, 'scheduled', ?, NULL)
            """,
            (
                acc1,
                posted_at_iso,
                posted_at_iso,
                acc1,
                posted_at_iso,
                acc2,
                tomorrow_slot_iso,
                acc2,
                over_2d_iso,
            ),
        )
        conn.execute(
            """
            INSERT INTO ai_usage (day, role, provider, model, route, kind, cost_usd)
            VALUES
                (?, 'vision', 'claude_cli', 'claude-code-pro', 'subscription', 'describe', 0.0),
                (?, 'writer', 'claude_cli', 'claude-code-pro', 'subscription', 'plan', 0.0),
                (?, 'checker', 'claude_api', 'claude-haiku-5-5', 'api', 'check', 0.12)
            """,
            (day_str, day_str, day_str),
        )

    summary = daily_summary(paths, now_dt=now_utc)
    assert "Đã đăng hôm nay: 1" in summary
    assert "Bài lỗi / lỡ lịch: 1" in summary
    assert "Đang chờ duyệt: 2" in summary
    assert "Lịch đăng ngày mai: 1" in summary
    assert "Xếp hàng > 2 ngày: 1" in summary
    assert "Lượt AI gói thuê bao: 2 lượt ($0.00)" in summary
    assert "Lượt AI trả phí (API): 1 lượt ($0.12 / $5.00)" in summary


@pytest.mark.local
def test_nightly_backup_retention_and_disk_cleanup(tmp_path: Path) -> None:
    app = create_app(data_dir=tmp_path, start_worker=False)
    paths = app.state.paths

    cfg = load_settings(paths.config_file)
    cfg.retention.backup_keep = 2
    cfg.retention.output_days = 90
    save_settings(paths.config_file, cfg)

    # Create raw footage (must NEVER be deleted) and old posted output (> 90 days old)
    raw_ftg = paths.footage_dir / "1.mp4"
    raw_ftg.parent.mkdir(parents=True, exist_ok=True)
    raw_ftg.write_bytes(b"raw_footage_content")

    old_out = paths.output_dir / "video_1.mp4"
    old_out.parent.mkdir(parents=True, exist_ok=True)
    old_out.write_bytes(b"old_rendered_master")

    work_sub = paths.work_dir / "video_1"
    work_sub.mkdir(parents=True, exist_ok=True)
    (work_sub / "seg_00.mp4").write_bytes(b"temp_seg")

    base_utc = datetime(2026, 11, 14, 2, 30, 0, tzinfo=timezone.utc)
    old_created_iso = (base_utc - timedelta(days=100)).strftime("%Y-%m-%dT%H:%M:%SZ")

    with get_conn(paths.db_file) as conn:
        conn.execute(
            """
            INSERT INTO videos (id, status, output_path, created_at)
            VALUES (1, 'posted', 'output/video_1.mp4', ?)
            """,
            (old_created_iso,),
        )

    # Run 3 backups across 3 nights with backup_keep=2 -> only 2 newest backups remain
    for night in range(3):
        res = run_nightly_backup_and_cleanup(
            paths,
            now_dt=base_utc + timedelta(days=night),
            free_bytes_override=LOW_DISK_THRESHOLD_BYTES - 1024,
        )
        assert res["low_disk"] is True

    db_backups = list(paths.backups_dir.glob("backup_*_app.db"))
    assert len(db_backups) == 2
    # Secrets file is never backed up automatically in backups_dir
    assert list(paths.backups_dir.glob("*secrets*")) == []

    # Old output file deleted, work_dir cleaned, DB record preserved, footage untouched!
    assert not old_out.exists()
    assert not work_sub.exists()
    assert raw_ftg.exists()
    assert query_one(paths.db_file, "SELECT id FROM videos WHERE id = 1") is not None

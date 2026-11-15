"""Real SQLite tests for auto-slot calculation, 7-video multi-day overflow, and 7h missed-slot protection (Phase 10)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from videocreator.app import create_app
from videocreator.approvals import approve
from videocreator.db import get_conn, query_all, query_one
from videocreator.posting.accounts import upsert_account
from videocreator.posting.post_actions import retry_failed_post
from videocreator.posting.publish import publish_due_posts


@pytest.mark.local
def test_seven_consecutive_approvals_fill_five_slots_today_and_two_tomorrow(
    tmp_path: Path,
) -> None:
    app = create_app(data_dir=tmp_path, start_worker=False)
    paths = app.state.paths

    acc_id = upsert_account(
        paths,
        platform="facebook",
        external_id="page_slots_1",
        name="FB Slots 1",
        access_token="tok_slots_secret_123",
    )

    with get_conn(paths.db_file) as conn:
        for vid in range(1, 8):
            conn.execute(
                "INSERT INTO videos (id, status, plan_json) VALUES (?, 'pending_approval', '{}')",
                (vid,),
            )

    tz_ict = ZoneInfo("Asia/Ho_Chi_Minh")
    # 07:00 ICT on 2026-11-14 -> all 5 default slots (08:00, 11:30, 15:00, 19:00, 21:00) are ahead today
    now_local = datetime(2026, 11, 14, 7, 0, 0, tzinfo=tz_ict)
    now_utc = now_local.astimezone(timezone.utc)

    for vid in range(1, 8):
        won = approve(
            paths.db_file,
            vid,
            by="ui",
            target_account_ids=[acc_id],
            config_file=paths.config_file,
            now_dt=now_utc,
        )
        assert won is True
        v_row = query_one(paths.db_file, "SELECT status FROM videos WHERE id = ?", (vid,))
        assert v_row is not None and v_row["status"] == "scheduled"

    posts = query_all(
        paths.db_file,
        "SELECT video_id, scheduled_at FROM posts WHERE account_id = ? ORDER BY scheduled_at ASC",
        (acc_id,),
    )
    assert len(posts) == 7

    # Convert scheduled_at back to Asia/Ho_Chi_Minh to verify 5 today + 2 tomorrow, zero duplicates
    local_slots = []
    for p in posts:
        iso_str = str(p["scheduled_at"]).replace("Z", "+00:00")
        dt_local = datetime.fromisoformat(iso_str).astimezone(tz_ict)
        local_slots.append((dt_local.strftime("%Y-%m-%d"), dt_local.strftime("%H:%M")))

    assert len(set(local_slots)) == 7  # No duplicate slots!
    today_slots = [hm for d, hm in local_slots if d == "2026-11-14"]
    tomorrow_slots = [hm for d, hm in local_slots if d == "2026-11-15"]
    assert today_slots == ["08:00", "11:30", "15:00", "19:00", "21:00"]
    assert tomorrow_slots == ["08:00", "11:30"]


@pytest.mark.local
def test_post_overdue_by_7_hours_becomes_missed_and_can_be_retried(
    tmp_path: Path,
) -> None:
    app = create_app(data_dir=tmp_path, start_worker=False)
    paths = app.state.paths

    acc_id = upsert_account(
        paths,
        platform="instagram",
        external_id="ig_missed_1",
        name="IG Missed",
        access_token="tok_missed_secret_123",
    )

    t_sched = datetime(2026, 11, 14, 1, 0, 0, tzinfo=timezone.utc)
    with get_conn(paths.db_file) as conn:
        conn.execute(
            "INSERT INTO videos (id, status, output_path) VALUES (10, 'scheduled', 'output/v10.mp4')"
        )
        conn.execute(
            """
            INSERT INTO posts (id, video_id, account_id, status, scheduled_at)
            VALUES (100, 10, ?, 'scheduled', ?)
            """,
            (acc_id, t_sched.strftime("%Y-%m-%dT%H:%M:%SZ")),
        )

    # Server comes back online 7 hours after scheduled_at (> 6h threshold)
    t_wake = t_sched + timedelta(hours=7)
    published_calls: list[int] = []

    class ShouldNotRunPoster:
        platform = "instagram"

        def publish(self, account, video_url, video_path, caption, post):
            published_calls.append(int(post["id"]))
            raise AssertionError("Should not publish a post overdue by 7 hours")

    processed = publish_due_posts(
        paths,
        poster_overrides={"instagram": ShouldNotRunPoster()},
        now_dt=t_wake,
    )
    assert processed == 1
    assert published_calls == []

    p_row = query_one(paths.db_file, "SELECT status, error FROM posts WHERE id = 100")
    assert p_row is not None
    assert p_row["status"] == "missed"
    assert "missed" in str(p_row["error"])

    v_row = query_one(paths.db_file, "SELECT status FROM videos WHERE id = 10")
    assert v_row is not None and v_row["status"] == "failed"

    # Manual retry resets post to scheduled and video to scheduled
    new_time = (t_wake + timedelta(minutes=15)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert retry_failed_post(paths.db_file, 100, scheduled_at_iso=new_time) is True

    p_retried = query_one(paths.db_file, "SELECT status, scheduled_at, error FROM posts WHERE id = 100")
    assert p_retried is not None
    assert p_retried["status"] == "scheduled"
    assert p_retried["scheduled_at"] == new_time
    assert p_retried["error"] is None

    v_retried = query_one(paths.db_file, "SELECT status FROM videos WHERE id = 10")
    assert v_retried is not None and v_retried["status"] == "scheduled"

    # Reschedule & Cancel via schedule UI routes
    with TestClient(app) as client:
        res_page = client.get("/schedule")
        assert res_page.status_code == 200
        assert "IG Missed" in res_page.text

        res_resched = client.post(
            "/posts/100/reschedule",
            data={"scheduled_at": "2026-11-15T09:00:00Z"},
            follow_redirects=True,
        )
        assert res_resched.status_code == 200
        p_after_resched = query_one(paths.db_file, "SELECT scheduled_at FROM posts WHERE id = 100")
        assert p_after_resched is not None and p_after_resched["scheduled_at"] == "2026-11-15T09:00:00Z"

        res_cancel = client.post("/posts/100/cancel", follow_redirects=True)
        assert res_cancel.status_code == 200
        assert query_one(paths.db_file, "SELECT id FROM posts WHERE id = 100") is None
        v_after_cancel = query_one(paths.db_file, "SELECT status FROM videos WHERE id = 10")
        assert v_after_cancel is not None and v_after_cancel["status"] == "approved"

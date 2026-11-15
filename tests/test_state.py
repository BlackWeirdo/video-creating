"""Real SQLite state machine and concurrency tests (no mocks)."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from videocreator.db import execute, migrate, query_one
from videocreator.state import InvalidTransitionError, transition, transition_footage
from videocreator.state_posts import transition_post

pytestmark = pytest.mark.local


def test_valid_and_invalid_video_transitions(tmp_path: Path) -> None:
    db_file = tmp_path / "app.db"
    migrate(db_file)
    vid = execute(db_file, "INSERT INTO videos (status) VALUES ('planned')")

    # Cannot jump directly from planned to approved
    with pytest.raises(InvalidTransitionError):
        transition(db_file, vid, "approved")

    assert transition(db_file, vid, "rendering") is True
    assert transition(db_file, vid, "rendered") is True
    assert transition(db_file, vid, "pending_approval") is True
    assert transition(db_file, vid, "approved", approved_by="tg:1001") is True

    row = query_one(
        db_file, "SELECT status, approved_by, approved_at FROM videos WHERE id = ?", (vid,)
    )
    assert row is not None
    assert row["status"] == "approved"
    assert row["approved_by"] == "tg:1001"
    assert row["approved_at"] is not None

    # Cannot transition backwards from approved to planned
    with pytest.raises(InvalidTransitionError):
        transition(db_file, vid, "planned")


def test_concurrent_duplicate_approvals_only_one_wins(tmp_path: Path) -> None:
    db_file = tmp_path / "app.db"
    migrate(db_file)
    vid = execute(db_file, "INSERT INTO videos (status) VALUES ('pending_approval')")

    def _attempt_approve(actor: str) -> bool:
        return transition(
            db_file,
            vid,
            "approved",
            expected_from="pending_approval",
            approved_by=actor,
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [
            pool.submit(_attempt_approve, f"tg:{user_id}")
            for user_id in (101, 102, 103, 104)
        ]
        outcomes = [f.result() for f in futures]

    assert outcomes.count(True) == 1
    assert outcomes.count(False) == 3

    row = query_one(db_file, "SELECT status, approved_by FROM videos WHERE id = ?", (vid,))
    assert row is not None
    assert row["status"] == "approved"
    assert str(row["approved_by"]).startswith("tg:")


def test_footage_and_post_transitions_update_video_status(tmp_path: Path) -> None:
    db_file = tmp_path / "app.db"
    migrate(db_file)

    ftg_id = execute(
        db_file,
        "INSERT INTO footage (path, sha256, status) VALUES ('a.mp4', 'sha1', 'imported')",
    )
    assert transition_footage(db_file, ftg_id, "analysing") is True
    assert transition_footage(db_file, ftg_id, "analysed") is True

    vid = execute(db_file, "INSERT INTO videos (status) VALUES ('scheduled')")
    acc1 = execute(
        db_file,
        "INSERT INTO accounts (platform, external_id, name, secret_key) VALUES ('facebook', 'p1', 'Page 1', 'sec1')",
    )
    acc2 = execute(
        db_file,
        "INSERT INTO accounts (platform, external_id, name, secret_key) VALUES ('tiktok', 't1', 'TikTok 1', 'sec2')",
    )
    post1 = execute(
        db_file,
        "INSERT INTO posts (video_id, account_id, status, scheduled_at) VALUES (?, ?, 'scheduled', '2026-11-13T10:00:00Z')",
        (vid, acc1),
    )
    post2 = execute(
        db_file,
        "INSERT INTO posts (video_id, account_id, status, scheduled_at) VALUES (?, ?, 'scheduled', '2026-11-13T10:00:00Z')",
        (vid, acc2),
    )

    assert transition_post(db_file, post1, "publishing") is True
    assert (
        transition_post(
            db_file,
            post1,
            "posted",
            external_post_id="fb_999",
            permalink="https://facebook.com/reel/999",
        )
        is True
    )
    # Second post still scheduled -> video still scheduled
    v_mid = query_one(db_file, "SELECT status FROM videos WHERE id = ?", (vid,))
    assert v_mid is not None and v_mid["status"] == "scheduled"

    assert transition_post(db_file, post2, "publishing") is True
    assert transition_post(db_file, post2, "needs_user_action") is True

    # Both posts are now in posted / needs_user_action -> video transitions to posted
    v_final = query_one(db_file, "SELECT status FROM videos WHERE id = ?", (vid,))
    assert v_final is not None and v_final["status"] == "posted"

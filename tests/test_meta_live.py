"""Live Meta (Facebook Page & Instagram Reels) publishing test (Phase 07)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from videocreator.posting.meta_auth import list_pages_and_instagram


@pytest.mark.live
def test_meta_live_discover_pages_and_ig(tmp_path: Path) -> None:
    token = os.environ.get("META_TEST_ACCESS_TOKEN")
    if not token:
        pytest.skip("META_TEST_ACCESS_TOKEN not configured for live Meta test")

    discovered = list_pages_and_instagram(token)
    assert isinstance(discovered, list)
    assert len(discovered) >= 1


@pytest.mark.live
def test_meta_live_reel_publish_then_retry_does_not_duplicate(tmp_path: Path) -> None:
    """Publishes ONE real public Reel on the test Page, then retries the same post: no second Reel.

    Needs META_TEST_PAGE_ID and META_TEST_PAGE_TOKEN (Page token with pages_manage_posts)."""
    import httpx

    from videocreator.db import get_conn, migrate, query_one
    from videocreator.paths import get_paths
    from videocreator.posting.facebook import FacebookPagePoster
    from videocreator.posting.meta_auth import GRAPH_BASE_URL
    from videocreator.secrets_store import SecretsStore

    page_id = os.environ.get("META_TEST_PAGE_ID")
    page_token = os.environ.get("META_TEST_PAGE_TOKEN")
    if not page_id or not page_token:
        pytest.skip("META_TEST_PAGE_ID / META_TEST_PAGE_TOKEN not configured for the live Reels test")

    paths = get_paths(tmp_path)
    migrate(paths.db_file)
    secrets = SecretsStore(paths.secrets_file)
    secrets.set("META_LIVE_PAGE", page_token)
    with get_conn(paths.db_file) as conn:
        conn.execute("INSERT INTO videos (id, status, plan_json) VALUES (1, 'scheduled', '{}')")
        conn.execute(
            "INSERT INTO accounts (id, platform, external_id, name, lang, secret_key, enabled) "
            "VALUES (1, 'facebook', ?, 'Live test', 'vi', 'META_LIVE_PAGE', 1)",
            (page_id,),
        )
        conn.execute("INSERT INTO posts (id, video_id, account_id, status, scheduled_at) VALUES (1, 1, 1, 'publishing', '2026-11-15T00:00:00Z')")

    def reel_count() -> int:
        resp = httpx.get(f"{GRAPH_BASE_URL}/{page_id}/video_reels", headers={"Authorization": f"Bearer {page_token}"},
                         params={"limit": "50"}, timeout=30.0)
        return len(resp.json().get("data") or [])

    poster = FacebookPagePoster(paths, secrets)
    account = query_one(paths.db_file, "SELECT * FROM accounts WHERE id = 1")
    clip = Path(__file__).parent / "samples" / "clip1_6s.mp4"
    first = poster.publish(account, "", clip, "Video Creator live test reel", query_one(paths.db_file, "SELECT * FROM posts WHERE id = 1"))
    assert first.status == "posted" and first.external_post_id
    print("Reel permalink:", first.permalink)
    before = reel_count()

    # Retry with the saved reel id (as after a lost reply): status is read first, nothing new is created.
    # While Meta is still publishing, the poster asks to be retried later (TransientPostError).
    import time

    from videocreator.posting.base import TransientPostError

    for _ in range(12):
        try:
            again = poster.publish(account, "", clip, "Video Creator live test reel", query_one(paths.db_file, "SELECT * FROM posts WHERE id = 1"))
            break
        except TransientPostError:
            time.sleep(10)
    else:
        pytest.fail("Reel still not published after 2 minutes")
    assert again.external_post_id == first.external_post_id
    assert reel_count() == before

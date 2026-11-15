"""Publishes due posts: claim, R2 staging, platform adapters, retry backoff and Telegram alerts (Phase 07)."""
from __future__ import annotations
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from videocreator.db import get_conn, query_all, query_one
from videocreator.paths import AppPaths
from videocreator.posting.base import Poster, TransientPostError
from videocreator.posting.captions import format_platform_caption
from videocreator.posting.facebook import FacebookPagePoster
from videocreator.posting.instagram import InstagramReelsPoster
from videocreator.posting.oauth_refresh import refresh_token_if_needed
from videocreator.posting.publish_outcomes import (
    fail_post,
    handle_permanent_failure,
    handle_transient_failure,
    mark_missed,
    notify_published,
)
from videocreator.posting.service import is_posting_paused, utc_now_iso
from videocreator.posting.storage_r2 import upload_to_r2
from videocreator.posting.threads import ThreadsPoster
from videocreator.posting.tiktok import TikTokPoster
from videocreator.secrets_store import SecretsStore
from videocreator.state_posts import transition_post
from videocreator.timeutil import parse_iso_utc, utc_now

logger = logging.getLogger("videocreator.posting.publish")

MISSED_THRESHOLD_HOURS = 6
# Platforms that fetch the video from a public URL (R2); Facebook and TikTok receive the file itself.
PUBLIC_URL_PLATFORMS = frozenset({"instagram", "threads"})

R2Uploader = Callable[[Path], tuple[str, str]]


def build_default_posters(
    paths: AppPaths, secrets_store: SecretsStore | None = None
) -> dict[str, Poster]:
    sec = secrets_store or SecretsStore(paths.secrets_file)
    return {
        "facebook": FacebookPagePoster(paths, sec),
        "instagram": InstagramReelsPoster(paths, sec),
        "threads": ThreadsPoster(paths, sec),
        "tiktok": TikTokPoster(paths, sec),
    }


def _query_due_posts(db_file: Path, now_iso: str) -> list[dict[str, Any]]:
    return query_all(
        db_file,
        """
        SELECT p.*, a.platform, a.external_id, a.name AS account_name,
               a.secret_key, a.token_expires_at, a.enabled
        FROM posts p
        JOIN accounts a ON p.account_id = a.id
        WHERE p.status = 'scheduled'
          AND a.enabled = 1
          AND p.scheduled_at <= ?
          AND (p.next_attempt_at IS NULL OR p.next_attempt_at <= ?)
        ORDER BY p.scheduled_at ASC, p.id ASC
        """,
        (now_iso, now_iso),
    )


def _is_overdue(post_row: dict[str, Any], now_utc: datetime) -> bool:
    scheduled_dt = parse_iso_utc(str(post_row.get("scheduled_at") or ""))
    return scheduled_dt is not None and (now_utc - scheduled_dt) > timedelta(hours=MISSED_THRESHOLD_HOURS)


def _staged_video_url(
    paths: AppPaths,
    video_row: dict[str, Any],
    video_path: Path,
    staged_urls: dict[int, str],
    r2_uploader: R2Uploader | None,
) -> str:
    """`FR-PST-05`: one R2 upload per video, reused by every account and every retry."""
    video_id = int(video_row["id"])
    if video_id in staged_urls:
        return staged_urls[video_id]
    if video_row.get("r2_url"):
        staged_urls[video_id] = str(video_row["r2_url"])
        return staged_urls[video_id]
    obj_key, pub_url = r2_uploader(video_path) if r2_uploader is not None else upload_to_r2(paths, video_path)
    with get_conn(paths.db_file) as conn:
        conn.execute("UPDATE videos SET r2_key = ?, r2_url = ? WHERE id = ?", (obj_key, pub_url, video_id))
    staged_urls[video_id] = pub_url
    return pub_url


def _publish_one_post(
    paths: AppPaths,
    post_row: dict[str, Any],
    *,
    posters: dict[str, Poster],
    staged_urls: dict[int, str],
    r2_uploader: R2Uploader | None,
    now_utc: datetime,
) -> bool:
    """Handles one due post. Returns False only when another worker already took it."""
    post_id = int(post_row["id"])
    video_id = int(post_row["video_id"])
    platform = str(post_row["platform"])

    # A post with a platform container/reel id already started publishing on time; it is finished,
    # never marked missed (otherwise it could be published while the app thinks it was not).
    if _is_overdue(post_row, now_utc) and not str(post_row.get("remote_container_id") or "").strip():
        return mark_missed(paths, post_row)

    # Atomically claim the post by transitioning scheduled -> publishing
    if not transition_post(paths.db_file, post_id, "publishing", expected_from="scheduled"):
        return False

    video_row = query_one(paths.db_file, "SELECT * FROM videos WHERE id = ?", (video_id,))
    if video_row is None or not video_row.get("output_path"):
        fail_post(paths.db_file, post_id, "Missing rendered output video")
        return True
    poster = posters.get(platform)
    if poster is None:
        fail_post(paths.db_file, post_id, f"No poster adapter registered for platform '{platform}'")
        return True

    video_path = paths.media_dir / str(video_row["output_path"])
    try:
        try:
            refresh_token_if_needed(paths, post_row, now_dt=now_utc)
        except Exception as ref_exc:
            logger.warning("Token refresh check failed for account %s: %s", post_row.get("account_id"), ref_exc)

        if platform in PUBLIC_URL_PLATFORMS:
            _staged_video_url(paths, video_row, video_path, staged_urls, r2_uploader)
        video_url = staged_urls.get(video_id, "")
        result = poster.publish(
            account=post_row,
            video_url=video_url,
            video_path=video_path,
            caption=format_platform_caption(video_row, platform),
            post=post_row,
        )
        transition_post(
            paths.db_file,
            post_id,
            result.status,
            expected_from="publishing",
            external_post_id=result.external_post_id,
            permalink=result.permalink,
            error=None,
            posted_at=utc_now_iso(now_utc) if result.status == "posted" else None,
        )
        notify_published(paths, post_row, result)
    except TransientPostError as exc:
        handle_transient_failure(paths, post_row, exc, now_utc)
    except Exception as exc:
        handle_permanent_failure(paths, post_row, exc)
    return True


def publish_due_posts(
    paths: AppPaths,
    *,
    poster_overrides: dict[str, Poster] | None = None,
    r2_uploader: R2Uploader | None = None,
    now_dt: datetime | None = None,
) -> int:
    """Publishes all due `scheduled` posts (`scheduled_at <= now` and `next_attempt_at <= now`)."""
    if is_posting_paused(paths.db_file):
        return 0

    now_utc = utc_now(now_dt)
    due_rows = _query_due_posts(paths.db_file, utc_now_iso(now_utc))
    if not due_rows:
        return 0

    posters = poster_overrides or build_default_posters(paths)
    staged_urls: dict[int, str] = {}
    processed_count = 0
    for post_row in due_rows:
        if _publish_one_post(
            paths, post_row, posters=posters, staged_urls=staged_urls, r2_uploader=r2_uploader, now_utc=now_utc
        ):
            processed_count += 1
    return processed_count

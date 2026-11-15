"""Pasted Facebook / Instagram video links as trend items (web form and Telegram `/link`).

The owner finds a good Reel by hand (Facebook Reels feed, a Page, a Profile) and pastes the
link. The app reads that one public video's metadata with the pinned yt-dlp (no login, no
cookies, `BR-REF-04`), stores it as a trend item flagged `pinned`, and queues `analyse_trend`
so it is downloaded, analysed with rea-video and offered for suggestions ahead of scanned items.
"""
from __future__ import annotations
import json
import logging
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from videocreator.db import get_conn, query_one, record_audit
from videocreator.jobs import enqueue_job
from videocreator.paths import AppPaths
from videocreator.timeutil import utc_now
from videocreator.trends.base import TrendItem
from videocreator.trends.download import find_yt_dlp_command
from videocreator.trends.link_parse import classify_video_url, parse_single_video
from videocreator.trends.scan import upsert_trend_item

logger = logging.getLogger("videocreator.trends.links")

ANALYSE_TREND_JOB_KIND = "analyse_trend"
MAX_PASTED_LINKS_PER_DAY = 20
YTDLP_TIMEOUT_S = 90


def _pasted_count_key(day: str) -> str:
    return f"pasted_links:{day}"


def _today_key(now_dt: datetime | None) -> str:
    return _pasted_count_key(utc_now(now_dt).strftime("%Y-%m-%d"))


def _check_daily_cap(db_file: Path, *, now_dt: datetime | None = None) -> None:
    row = query_one(db_file, "SELECT value FROM settings WHERE key = ?", (_today_key(now_dt),))
    used = int(row["value"]) if row and str(row["value"]).isdigit() else 0
    if used >= MAX_PASTED_LINKS_PER_DAY:
        raise ValueError(f"Đã đủ {MAX_PASTED_LINKS_PER_DAY} link hôm nay. Hãy thử lại vào ngày mai.")


def _count_link(db_file: Path, *, now_dt: datetime | None = None) -> None:
    """Counts one successfully read link (failed reads and typos do not use the day's slots)."""
    with get_conn(db_file) as conn:
        conn.execute(
            """
            INSERT INTO settings (key, value) VALUES (?, '1')
            ON CONFLICT(key) DO UPDATE SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT)
            """,
            (_today_key(now_dt),),
        )


def read_video_metadata(url: str) -> dict[str, Any]:
    """Runs the pinned yt-dlp for ONE public video, metadata only. Messages never embed stderr."""
    # --ignore-config: a user-level yt-dlp.conf (cookies...) must never apply (BR-REF-04).
    cmd = [*find_yt_dlp_command(), "--ignore-config", "--skip-download", "--no-playlist", "-J", "--no-warnings", "--", url]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=YTDLP_TIMEOUT_S, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError("Nền tảng không trả lời kịp. Hãy thử lại sau.") from exc
    if proc.returncode != 0 or not proc.stdout.strip():
        logger.info("yt-dlp could not read %s: %s", url, proc.stderr[-500:])
        raise ValueError(
            "Không đọc được video này khi không đăng nhập (video riêng tư, đã xoá, hoặc nền tảng chặn). "
            "Hãy tải file về rồi bấm 'Nạp video tham khảo' ở bài tương ứng."
        )
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("yt-dlp trả về dữ liệu không đọc được. Hãy thử lại sau.") from exc
    if not isinstance(data, dict):
        raise ValueError("yt-dlp trả về dữ liệu không đọc được. Hãy thử lại sau.")
    return data


def add_pasted_link(
    paths: AppPaths,
    url: str,
    *,
    actor: str = "ui",
    now_dt: datetime | None = None,
) -> tuple[int, TrendItem]:
    """Validates, reads, stores and queues analysis for one pasted video link."""
    platform, clean_url = classify_video_url(url)
    _check_daily_cap(paths.db_file, now_dt=now_dt)
    data = read_video_metadata(clean_url)
    item = parse_single_video(data, platform=platform, url=clean_url, now_dt=now_dt)
    _count_link(paths.db_file, now_dt=now_dt)
    trend_id = upsert_trend_item(paths.db_file, item, now_dt=now_dt)

    row = query_one(paths.db_file, "SELECT analysis_json FROM trend_items WHERE id = ?", (trend_id,))
    if row is not None and not row.get("analysis_json"):
        enqueue_job(paths.db_file, ANALYSE_TREND_JOB_KIND, ref_id=trend_id)
    with get_conn(paths.db_file) as conn:
        record_audit(
            conn, actor=actor, action="trends.link_added", object_type="trend_item",
            object_id=trend_id, detail=clean_url,
        )
    return trend_id, item


def run_analyse_trend_job(paths: AppPaths, trend_item_id: int) -> str:
    """Job handler for `analyse_trend`: analyse one pasted video, then refresh suggestions."""
    from videocreator.trends.analyse import analyse_trend_item
    from videocreator.trends.suggest import make_suggestions

    row = query_one(paths.db_file, "SELECT analysis_json FROM trend_items WHERE id = ?", (trend_item_id,))
    if row is None:
        return f"Trend item #{trend_item_id} no longer exists"
    if row.get("analysis_json"):
        return f"Trend item #{trend_item_id} was already analysed; nothing to do"
    # Hand-picked videos have their own daily cap, so they skip the scan's download cap.
    analyse_trend_item(paths, trend_item_id, ignore_download_cap=True)
    ref = query_one(
        paths.db_file,
        "SELECT path FROM reference_videos WHERE trend_item_id = ? AND deleted_at IS NULL",
        (trend_item_id,),
    )
    made = make_suggestions(paths)
    how = "with the downloaded video (rea-video)" if ref else "from metrics and caption only (video could not be downloaded)"
    return f"Analysed trend item #{trend_item_id} {how}; suggestions created: {len(made)}"

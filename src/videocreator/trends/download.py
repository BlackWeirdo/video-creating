"""Reference video downloader (`yt-dlp` subprocess, top-N/day limit, 7-day auto-cleanup, `BR-REF-01..03`, Phase 13)."""
from __future__ import annotations
import ipaddress
import logging
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from videocreator.config import load_settings
from videocreator.db import get_conn, query_all, query_one
from videocreator.paths import AppPaths, find_ffmpeg_binary
from videocreator.ai.budget import app_timezone
from videocreator.timeutil import UTC_ISO_FORMAT, local_day_start_utc_iso, utc_now

logger = logging.getLogger("videocreator.trends.download")


def _is_safe_public_http_url(url: str) -> bool:
    raw = (url or "").strip()
    if not raw or raw.startswith("-"):
        return False
    parsed = urlsplit(raw)
    if parsed.scheme.lower() not in ("http", "https"):
        return False
    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if not host or host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return True
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def find_yt_dlp_command() -> list[str]:
    venv_exe = Path(sys.executable).parent / ("yt-dlp.exe" if sys.platform == "win32" else "yt-dlp")
    if venv_exe.exists():
        return [str(venv_exe)]
    which_exe = shutil.which("yt-dlp")
    if which_exe:
        return [which_exe]
    return [sys.executable, "-m", "yt_dlp"]


def _default_yt_dlp_download(url: str, dest_path: Path) -> bool:
    if not _is_safe_public_http_url(url):
        logger.warning("Rejected unsafe reference video URL: %s", url)
        return False
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        *find_yt_dlp_command(),
        # A user-level yt-dlp.conf (e.g. --cookies-from-browser) must never apply (BR-REF-04).
        "--ignore-config",
        "--no-playlist",
        "--no-warnings",
        "--max-filesize",
        "80M",
        # Video WITH audio (the analysis reads music and pacing), H.264 up to 1080p preferred, merged to MP4.
        # A bare "mp4" selector returned a video-only AV1 stream when run for real.
        "-f",
        "bv*[height<=1080]+ba/b[height<=1080]/b",
        "-S",
        "vcodec:h264,res:1080,acodec:m4a",
        "--merge-output-format",
        "mp4",
        "--ffmpeg-location",
        str(Path(find_ffmpeg_binary("ffmpeg")).parent),
        "-o",
        str(dest_path),
        "--",
        url.strip(),
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=240,
            check=False,
        )
        return proc.returncode == 0 and dest_path.exists() and dest_path.stat().st_size > 0
    except Exception as exc:
        logger.warning("yt-dlp failed for %s: %s", url, exc)
        return False


def count_today_reference_downloads(
    db_file: Path, now_dt: datetime | None = None
) -> int:
    day_start = local_day_start_utc_iso(app_timezone(db_file), now_dt)
    row = query_one(
        db_file,
        "SELECT COUNT(*) AS c FROM reference_videos WHERE downloaded_at >= ?",
        (day_start,),
    )
    return int(row["c"]) if row else 0


def fetch_reference_video(
    paths: AppPaths,
    trend_item_id: int,
    *,
    downloader_fn: Callable[[str, Path], bool] | None = None,
    now_dt: datetime | None = None,
    ignore_daily_cap: bool = False,
) -> Path | None:
    """Downloads a top trend video into `media/reference/` (never into `shots` or `footage`, `BR-REF-01..03`).

    `ignore_daily_cap` is for videos the owner pasted by hand: they have their own daily cap
    (`trends/links.py`) and must not lose their file to the scan's top-N downloads.
    """
    item_row = query_one(
        paths.db_file,
        "SELECT id, url FROM trend_items WHERE id = ?",
        (trend_item_id,),
    )
    if item_row is None:
        return None
    raw_url = str(item_row.get("url") or "")
    if not _is_safe_public_http_url(raw_url):
        logger.warning("Rejected unsafe trend URL on item #%d: %s", trend_item_id, raw_url)
        return None

    existing = query_one(
        paths.db_file,
        "SELECT path, deleted_at FROM reference_videos WHERE trend_item_id = ?",
        (trend_item_id,),
    )
    if existing and existing.get("path") and not existing.get("deleted_at"):
        p = paths.media_dir / str(existing["path"])
        if p.exists():
            return p

    cfg = load_settings(paths.config_file)
    base_utc = utc_now(now_dt)
    if not ignore_daily_cap and count_today_reference_downloads(paths.db_file, now_dt=base_utc) >= max(1, cfg.trends.download_top_n):
        logger.info("Reached daily reference video download cap (%d/day)", cfg.trends.download_top_n)
        return None

    paths.reference_dir.mkdir(parents=True, exist_ok=True)
    rel_path = f"reference/ref_{trend_item_id}.mp4"
    dest_file = paths.media_dir / rel_path

    dl = downloader_fn or _default_yt_dlp_download
    ok = dl(str(item_row["url"]), dest_file)
    if not ok or not dest_file.exists():
        return None

    dl_iso = base_utc.strftime(UTC_ISO_FORMAT)
    with get_conn(paths.db_file) as conn:
        conn.execute(
            """
            INSERT INTO reference_videos (trend_item_id, path, downloaded_at, deleted_at)
            VALUES (?, ?, ?, NULL)
            ON CONFLICT(trend_item_id) DO UPDATE SET
                path = excluded.path,
                downloaded_at = excluded.downloaded_at,
                deleted_at = NULL
            """,
            (trend_item_id, rel_path, dl_iso),
        )
    return dest_file


def cleanup_expired_reference_videos(
    paths: AppPaths,
    now_dt: datetime | None = None,
) -> int:
    """Deletes reference `.mp4` files older than `trends.reference_keep_days` (default 7 days), while keeping `rea_dir` (`BR-REF-02`)."""
    cfg = load_settings(paths.config_file)
    keep_days = max(1, int(cfg.trends.reference_keep_days))
    base_utc = utc_now(now_dt)
    cutoff_iso = (base_utc - timedelta(days=keep_days)).strftime(UTC_ISO_FORMAT)
    now_iso = base_utc.strftime(UTC_ISO_FORMAT)

    rows = query_all(
        paths.db_file,
        """
        SELECT id, path, rea_dir
        FROM reference_videos
        WHERE deleted_at IS NULL AND downloaded_at < ?
        """,
        (cutoff_iso,),
    )
    cleaned = 0
    for r in rows:
        rel = str(r.get("path") or "")
        if rel and rel.startswith("reference"):
            mp4_file = paths.media_dir / rel
            if mp4_file.exists():
                mp4_file.unlink(missing_ok=True)
        with get_conn(paths.db_file) as conn:
            conn.execute(
                "UPDATE reference_videos SET deleted_at = ? WHERE id = ?",
                (now_iso, int(r["id"])),
            )
        cleaned += 1

    return cleaned

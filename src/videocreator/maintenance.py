"""Housekeeping jobs: expiring-token warnings, nightly DB backup, disk retention (Phase 10 & 15)."""
from __future__ import annotations
import logging
import shutil
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from videocreator.config import load_settings
from videocreator.db import query_all
from videocreator.paths import AppPaths
from videocreator.tg.sender import send_text
from videocreator.timeutil import UTC_ISO_FORMAT, parse_iso_utc, utc_now

logger = logging.getLogger("videocreator.reports")

LOW_DISK_THRESHOLD_BYTES = 10 * 1024 * 1024 * 1024  # 10 GB


def check_expiring_tokens(
    paths: AppPaths,
    now_dt: datetime | None = None,
    *,
    warn_within_days: int = 7,
) -> list[dict[str, Any]]:
    """Checks `accounts.token_expires_at` and alerts Telegram for tokens expiring within `warn_within_days` (`FR-PST-11`)."""
    base_utc = utc_now(now_dt)
    cutoff_utc = base_utc + timedelta(days=warn_within_days)
    rows = query_all(
        paths.db_file,
        """
        SELECT id, platform, name, token_expires_at
        FROM accounts
        WHERE enabled = 1 AND token_expires_at IS NOT NULL AND token_expires_at != ''
        ORDER BY id ASC
        """,
    )
    expiring: list[dict[str, Any]] = []
    for r in rows:
        exp_dt = parse_iso_utc(r.get("token_expires_at"))
        if exp_dt is None:
            continue
        if exp_dt <= cutoff_utc:
            days_left = (exp_dt - base_utc).total_seconds() / 86400.0
            item = {
                "id": int(r["id"]),
                "platform": str(r["platform"]),
                "name": str(r["name"]),
                "token_expires_at": str(r["token_expires_at"]),
                "days_left": round(days_left, 1),
            }
            expiring.append(item)

    if expiring:
        msg_lines = ["⚠️ Cảnh báo token sắp hết hạn (< 7 ngày):"]
        for item in expiring:
            msg_lines.append(
                f"• {item['platform']} ({item['name']}): còn {item['days_left']} ngày ({item['token_expires_at']})"
            )
        msg_lines.append("Vào trang Tài khoản để làm mới hoặc kết nối lại.")
        try:
            send_text(paths, "\n".join(msg_lines), topic="alerts")
        except Exception:
            pass

    return expiring


def _backup_database(paths: AppPaths, stamp: str) -> Path:
    """Copies `app.db` (SQLite online backup) and `config.toml`; never `secrets.bin`."""
    paths.backups_dir.mkdir(parents=True, exist_ok=True)
    db_backup_path = paths.backups_dir / f"backup_{stamp}_app.db"
    cfg_backup_path = paths.backups_dir / f"backup_{stamp}_config.toml"
    try:
        src_conn = sqlite3.connect(str(paths.db_file))
        dst_conn = sqlite3.connect(str(db_backup_path))
        with dst_conn:
            src_conn.backup(dst_conn)
        dst_conn.close()
        src_conn.close()
        if paths.config_file.exists():
            shutil.copy2(paths.config_file, cfg_backup_path)
    except Exception as exc:
        logger.error("Nightly backup failed: %s", exc)
        try:
            send_text(paths, f"❌ Lỗi sao lưu tự động ban đêm: {exc}")
        except Exception:
            pass
        raise
    return db_backup_path


def _prune_old_backups(backups_dir: Path, keep_count: int) -> int:
    db_backups = sorted(backups_dir.glob("backup_*_app.db"))
    stale = db_backups[: max(0, len(db_backups) - keep_count)]
    for old_db in stale:
        prefix = old_db.name.replace("_app.db", "")
        old_db.unlink(missing_ok=True)
        (backups_dir / f"{prefix}_config.toml").unlink(missing_ok=True)
    return len(stale)


def _clean_finished_work_dirs(paths: AppPaths) -> int:
    """Removes `work/video_<id>` folders of videos that reached a final state."""
    if not paths.work_dir.exists():
        return 0
    finished_rows = query_all(
        paths.db_file,
        "SELECT id FROM videos WHERE status IN ('posted', 'rejected', 'failed', 'superseded')",
    )
    finished_ids = {int(r["id"]) for r in finished_rows}
    cleaned = 0
    for child in paths.work_dir.iterdir():
        if not child.is_dir() or not child.name.startswith("video_"):
            continue
        suffix = child.name.removeprefix("video_")
        if suffix.isdigit() and int(suffix) in finished_ids:
            shutil.rmtree(child, ignore_errors=True)
            cleaned += 1
    return cleaned


def _prune_old_outputs(paths: AppPaths, cutoff_iso: str) -> int:
    """Deletes master MP4s of posted videos created before `cutoff_iso` (the DB row and footage stay)."""
    old_posted = query_all(
        paths.db_file,
        """
        SELECT id, output_path
        FROM videos
        WHERE status = 'posted'
          AND output_path IS NOT NULL
          AND created_at < ?
        """,
        (cutoff_iso,),
    )
    pruned = 0
    for video in old_posted:
        rel = str(video["output_path"])
        # Safety check: never touch anything inside footage/
        if rel.startswith("footage"):
            continue
        output_file = paths.media_dir / rel
        if output_file.exists():
            output_file.unlink(missing_ok=True)
            pruned += 1
    return pruned


def _alert_if_disk_low(paths: AppPaths, free_bytes: int) -> bool:
    if free_bytes >= LOW_DISK_THRESHOLD_BYTES:
        return False
    try:
        send_text(
            paths,
            f"⚠️ Cảnh báo ổ đĩa sắp đầy: chỉ còn {free_bytes / (1024**3):.1f} GB trống (< 10 GB).",
            topic="alerts",
        )
    except Exception:
        pass
    return True


def run_nightly_backup_and_cleanup(
    paths: AppPaths,
    now_dt: datetime | None = None,
    *,
    free_bytes_override: int | None = None,
) -> dict[str, Any]:
    """Runs nightly SQLite backup (`app.db` + `config.toml`, never `secrets.bin`), prunes old backups & old outputs, and checks disk space."""
    cfg = load_settings(paths.config_file)
    base_utc = utc_now(now_dt)

    db_backup_path = _backup_database(paths, base_utc.strftime("%Y%m%d_%H%M%S"))
    pruned_backups = _prune_old_backups(paths.backups_dir, max(1, int(cfg.retention.backup_keep)))
    cleaned_work_dirs = _clean_finished_work_dirs(paths)
    cutoff_iso = (
        base_utc - timedelta(days=max(1, int(cfg.retention.output_days)))
    ).strftime(UTC_ISO_FORMAT)
    pruned_outputs = _prune_old_outputs(paths, cutoff_iso)

    free_bytes = (
        free_bytes_override if free_bytes_override is not None else shutil.disk_usage(str(paths.data_dir)).free
    )
    return {
        "db_backup": str(db_backup_path),
        "pruned_backups": pruned_backups,
        "cleaned_work_dirs": cleaned_work_dirs,
        "pruned_outputs": pruned_outputs,
        "low_disk": _alert_if_disk_low(paths, free_bytes),
    }

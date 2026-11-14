"""Daily and weekly operational reports, token expiry checks, nightly DB backup, and disk retention (Phase 10 & Phase 15)."""
from __future__ import annotations

import json
import logging
import shutil
import sqlite3
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from videocreator.config import load_settings
from videocreator.db import get_conn, query_all, query_one
from videocreator.paths import AppPaths
from videocreator.telegram_bot import send_text

logger = logging.getLogger("videocreator.reports")

LOW_DISK_THRESHOLD_BYTES = 10 * 1024 * 1024 * 1024  # 10 GB


def _parse_iso_utc(iso_str: str | None) -> datetime | None:
    if not iso_str:
        return None
    try:
        clean = str(iso_str).strip()
        if clean.endswith("Z"):
            clean = clean[:-1] + "+00:00"
        dt = datetime.fromisoformat(clean)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def daily_summary(
    paths: AppPaths,
    now_dt: datetime | None = None,
) -> str:
    """Builds the Vietnamese daily report string (`FR-RPT-01`) for Telegram and `/report`."""
    cfg = load_settings(paths.config_file)
    tz = ZoneInfo(cfg.schedule.timezone)
    base_utc = (now_dt or datetime.now(timezone.utc)).astimezone(timezone.utc)
    base_local = base_utc.astimezone(tz)

    today_start_local = datetime.combine(base_local.date(), time(0, 0, 0), tzinfo=tz)
    tomorrow_start_local = today_start_local + timedelta(days=1)
    day_after_tomorrow_local = tomorrow_start_local + timedelta(days=1)

    today_start_iso = today_start_local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    tomorrow_start_iso = tomorrow_start_local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    day_after_iso = day_after_tomorrow_local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    two_days_later_iso = (base_utc + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")

    posted_today = query_one(
        paths.db_file,
        """
        SELECT COUNT(*) AS c FROM posts
        WHERE status = 'posted' AND posted_at >= ? AND posted_at < ?
        """,
        (today_start_iso, tomorrow_start_iso),
    )
    failed_posts = query_one(
        paths.db_file,
        "SELECT COUNT(*) AS c FROM posts WHERE status IN ('failed', 'missed')",
    )
    pending_approval = query_one(
        paths.db_file,
        "SELECT COUNT(*) AS c FROM videos WHERE status = 'pending_approval'",
    )
    tomorrow_scheduled = query_one(
        paths.db_file,
        """
        SELECT COUNT(*) AS c FROM posts
        WHERE status = 'scheduled' AND scheduled_at >= ? AND scheduled_at < ?
        """,
        (tomorrow_start_iso, day_after_iso),
    )
    queued_over_2d = query_one(
        paths.db_file,
        """
        SELECT COUNT(*) AS c FROM posts
        WHERE status = 'scheduled' AND scheduled_at > ?
        """,
        (two_days_later_iso,),
    )

    day_str = base_utc.strftime("%Y-%m-%d")
    sub_calls = query_one(
        paths.db_file,
        "SELECT COUNT(*) AS c FROM ai_usage WHERE day = ? AND route = 'subscription'",
        (day_str,),
    )
    api_stats = query_one(
        paths.db_file,
        """
        SELECT COUNT(*) AS c, COALESCE(SUM(cost_usd), 0.0) AS cost
        FROM ai_usage WHERE day = ? AND route = 'api'
        """,
        (day_str,),
    )

    n_posted = int(posted_today["c"]) if posted_today else 0
    n_failed = int(failed_posts["c"]) if failed_posts else 0
    n_pending = int(pending_approval["c"]) if pending_approval else 0
    n_tomorrow = int(tomorrow_scheduled["c"]) if tomorrow_scheduled else 0
    n_over2d = int(queued_over_2d["c"]) if queued_over_2d else 0
    n_sub = int(sub_calls["c"]) if sub_calls else 0
    n_api = int(api_stats["c"]) if api_stats else 0
    cost_api = float(api_stats["cost"]) if api_stats else 0.0

    lines = [
        f"📊 Báo cáo ngày ({base_local.strftime('%Y-%m-%d')})",
        f"• Đã đăng hôm nay: {n_posted}",
        f"• Bài lỗi / lỡ lịch: {n_failed}",
        f"• Đang chờ duyệt: {n_pending}",
        f"• Lịch đăng ngày mai: {n_tomorrow}",
        f"• Xếp hàng > 2 ngày: {n_over2d}",
        f"• Lượt AI gói thuê bao: {n_sub} lượt ($0.00)",
        f"• Lượt AI trả phí (API): {n_api} lượt (${cost_api:.2f} / ${cfg.budget.daily_usd:.2f})",
    ]
    return "\n".join(lines)


def check_expiring_tokens(
    paths: AppPaths,
    now_dt: datetime | None = None,
    *,
    warn_within_days: int = 7,
) -> list[dict[str, Any]]:
    """Checks `accounts.token_expires_at` and alerts Telegram for tokens expiring within `warn_within_days` (`FR-PST-11`)."""
    base_utc = (now_dt or datetime.now(timezone.utc)).astimezone(timezone.utc)
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
        exp_dt = _parse_iso_utc(r.get("token_expires_at"))
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


def run_nightly_backup_and_cleanup(
    paths: AppPaths,
    now_dt: datetime | None = None,
    *,
    free_bytes_override: int | None = None,
) -> dict[str, Any]:
    """Runs nightly SQLite backup (`app.db` + `config.toml`, never `secrets.bin`), prunes old backups & old outputs, and checks disk space."""
    cfg = load_settings(paths.config_file)
    base_utc = (now_dt or datetime.now(timezone.utc)).astimezone(timezone.utc)
    stamp = base_utc.strftime("%Y%m%d_%H%M%S")

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

    # Prune old backups beyond retention.backup_keep
    keep_n = max(1, int(cfg.retention.backup_keep))
    db_backups = sorted(paths.backups_dir.glob("backup_*_app.db"))
    pruned_backups = 0
    if len(db_backups) > keep_n:
        for old_db in db_backups[: len(db_backups) - keep_n]:
            prefix = old_db.name.replace("_app.db", "")
            old_cfg = paths.backups_dir / f"{prefix}_config.toml"
            old_db.unlink(missing_ok=True)
            old_cfg.unlink(missing_ok=True)
            pruned_backups += 1

    # Clean work/ subdirectories for finished videos
    cleaned_work_dirs = 0
    if paths.work_dir.exists():
        finished_rows = query_all(
            paths.db_file,
            "SELECT id FROM videos WHERE status IN ('posted', 'rejected', 'failed', 'superseded')",
        )
        finished_ids = {int(r["id"]) for r in finished_rows}
        for child in paths.work_dir.iterdir():
            if child.is_dir() and child.name.startswith("video_"):
                suffix = child.name.removeprefix("video_")
                if suffix.isdigit() and int(suffix) in finished_ids:
                    shutil.rmtree(child, ignore_errors=True)
                    cleaned_work_dirs += 1

    # Prune rendered master MP4s of posted videos older than retention.output_days (keep DB row & footage!)
    cutoff_iso = (
        base_utc - timedelta(days=max(1, int(cfg.retention.output_days)))
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
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
    pruned_outputs = 0
    for vr in old_posted:
        rel = str(vr["output_path"])
        # Safety check: never touch anything inside footage/
        if rel.startswith("footage"):
            continue
        f_path = paths.media_dir / rel
        if f_path.exists():
            f_path.unlink(missing_ok=True)
            pruned_outputs += 1

    # Check free disk space (< 10 GB -> alert Telegram)
    if free_bytes_override is not None:
        free_bytes = free_bytes_override
    else:
        usage = shutil.disk_usage(str(paths.data_dir))
        free_bytes = usage.free

    low_disk = free_bytes < LOW_DISK_THRESHOLD_BYTES
    if low_disk:
        free_gb = free_bytes / (1024**3)
        try:
            send_text(
                paths,
                f"⚠️ Cảnh báo ổ đĩa sắp đầy: chỉ còn {free_gb:.1f} GB trống (< 10 GB).",
                topic="alerts",
            )
        except Exception:
            pass

    return {
        "db_backup": str(db_backup_path),
        "pruned_backups": pruned_backups,
        "cleaned_work_dirs": cleaned_work_dirs,
        "pruned_outputs": pruned_outputs,
        "low_disk": low_disk,
    }


def weekly_summary(
    paths: AppPaths,
    now_dt: datetime | None = None,
) -> str:
    """Builds the Vietnamese weekly performance report (`FR-RPT-03`) for Telegram and `/report week`."""
    base_utc = (now_dt or datetime.now(timezone.utc)).astimezone(timezone.utc)
    week_ago_iso = (base_utc - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")

    plat_counts = query_all(
        paths.db_file,
        """
        SELECT a.platform, COUNT(*) AS c
        FROM posts p
        JOIN accounts a ON p.account_id = a.id
        WHERE p.status = 'posted' AND p.posted_at >= ?
        GROUP BY a.platform
        ORDER BY a.platform ASC
        """,
        (week_ago_iso,),
    )

    # Check 72h checkpoint metrics joined with videos
    metric_rows = query_all(
        paths.db_file,
        """
        SELECT pm.views, pm.likes, pm.comments, pm.shares,
               p.id AS post_id, p.video_id, a.platform,
               v.plan_json, v.suggestion_id
        FROM post_metrics pm
        JOIN posts p ON pm.post_id = p.id
        JOIN accounts a ON p.account_id = a.id
        JOIN videos v ON p.video_id = v.id
        WHERE pm.checkpoint = '72h' AND pm.views IS NOT NULL
        ORDER BY pm.views DESC, p.id ASC
        """,
    )

    lines = [f"📈 Báo cáo tuần (7 ngày tới {base_utc.strftime('%Y-%m-%d')})"]
    if plat_counts:
        plat_str = ", ".join(f"{r['platform']}: {r['c']}" for r in plat_counts)
        lines.append(f"• Đã đăng theo nền tảng: {plat_str}")
    else:
        lines.append("• Đã đăng theo nền tảng: 0 bài")

    if not metric_rows:
        lines.append("• Số liệu 72h: không có dữ liệu")
        return "\n".join(lines)

    top3 = metric_rows[:3]
    lines.append("• Top 3 bài theo lượt xem 72h:")
    for r in top3:
        lines.append(
            f"  - Video #{r['video_id']} ({r['platform']}): {r['views']} lượt xem, {r['likes'] or 0} thích"
        )

    if len(metric_rows) > 3:
        bottom3 = list(reversed(metric_rows[-3:]))
        lines.append("• Bottom 3 bài theo lượt xem 72h:")
        for r in bottom3:
            lines.append(
                f"  - Video #{r['video_id']} ({r['platform']}): {r['views']} lượt xem"
            )

    # Aggregate by formula and suggestion source
    by_formula: dict[str, list[int]] = {}
    trend_views: list[int] = []
    regular_views: list[int] = []

    for r in metric_rows:
        v_count = int(r["views"])
        formula = "hook-first"
        try:
            plan = json.loads(str(r.get("plan_json") or "{}"))
            formula = str(plan.get("formula") or "hook-first")
        except Exception:
            pass
        by_formula.setdefault(formula, []).append(v_count)
        if r.get("suggestion_id"):
            trend_views.append(v_count)
        else:
            regular_views.append(v_count)

    lines.append("• Trung bình lượt xem 72h theo công thức:")
    for fm, vals in sorted(
        by_formula.items(), key=lambda kv: sum(kv[1]) / len(kv[1]), reverse=True
    ):
        avg_v = sum(vals) / len(vals)
        lines.append(f"  - {fm}: {avg_v:.0f} lượt xem (mẫu n={len(vals)})")

    if trend_views or regular_views:
        t_avg = f"{sum(trend_views)/len(trend_views):.0f} (n={len(trend_views)})" if trend_views else "không có dữ liệu"
        r_avg = f"{sum(regular_views)/len(regular_views):.0f} (n={len(regular_views)})" if regular_views else "không có dữ liệu"
        lines.append(f"• Theo nguồn: Đề xuất xu hướng={t_avg} | Thường={r_avg}")

    return "\n".join(lines)

"""Daily and weekly operational reports, token expiry checks, nightly DB backup, and disk retention (Phase 10 & Phase 15)."""
from __future__ import annotations
import json
import logging
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from videocreator.config import load_settings
from videocreator.db import query_all, query_one
from videocreator.paths import AppPaths
from videocreator.timeutil import UTC_ISO_FORMAT, utc_now

logger = logging.getLogger("videocreator.reports")


def daily_summary(
    paths: AppPaths,
    now_dt: datetime | None = None,
) -> str:
    """Builds the Vietnamese daily report string (`FR-RPT-01`) for Telegram and `/report`."""
    cfg = load_settings(paths.config_file)
    tz = ZoneInfo(cfg.schedule.timezone)
    base_utc = utc_now(now_dt)
    base_local = base_utc.astimezone(tz)

    today_start_local = datetime.combine(base_local.date(), time(0, 0, 0), tzinfo=tz)
    tomorrow_start_local = today_start_local + timedelta(days=1)
    day_after_tomorrow_local = tomorrow_start_local + timedelta(days=1)

    today_start_iso = today_start_local.astimezone(timezone.utc).strftime(UTC_ISO_FORMAT)
    tomorrow_start_iso = tomorrow_start_local.astimezone(timezone.utc).strftime(UTC_ISO_FORMAT)
    day_after_iso = day_after_tomorrow_local.astimezone(timezone.utc).strftime(UTC_ISO_FORMAT)
    two_days_later_iso = (base_utc + timedelta(days=2)).strftime(UTC_ISO_FORMAT)

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


def weekly_summary(
    paths: AppPaths,
    now_dt: datetime | None = None,
) -> str:
    """Builds the Vietnamese weekly performance report (`FR-RPT-03`) for Telegram and `/report week`."""
    base_utc = utc_now(now_dt)
    week_ago_iso = (base_utc - timedelta(days=7)).strftime(UTC_ISO_FORMAT)

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

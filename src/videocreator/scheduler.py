"""APScheduler background service running on `role = 'server'` (Phase 07, 10, 12, 13, 14, 15, 16)."""
from __future__ import annotations

import asyncio
import logging
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from videocreator.config import load_settings
from videocreator.jobs import enqueue_job
from videocreator.maintenance import check_expiring_tokens, run_nightly_backup_and_cleanup
from videocreator.manual.tickets import expire_stale_tickets, scan_inbox_for_tickets
from videocreator.paths import AppPaths
from videocreator.posting.metrics import collect_due_metrics
from videocreator.posting.publish import publish_due_posts
from videocreator.posting.service import cleanup_staged_r2_objects
from videocreator.reports import daily_summary, weekly_summary
from videocreator.tg.notify import flush_deferred_notifications
from videocreator.tg.sender import send_text
from videocreator.timeutil import parse_dow_hhmm, parse_hhmm
from videocreator.trends.download import cleanup_expired_reference_videos

logger = logging.getLogger("videocreator.scheduler")


class AppScheduler:
    """Manages periodic background tasks on `role='server'`."""

    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths
        self._scheduler: AsyncIOScheduler | None = None

    def start(self) -> None:
        settings = load_settings(self.paths.config_file)
        if settings.role != "server":
            return
        if self._scheduler is not None and self._scheduler.running:
            return

        tz = ZoneInfo(settings.schedule.timezone)
        self._scheduler = AsyncIOScheduler(timezone=tz)

        # 1. Every 60s: publish due posts (with 6h missed-slot protection)
        self._scheduler.add_job(
            self._tick_publish_due,
            "interval",
            seconds=60,
            id="publish_due_posts",
            replace_existing=True,
            max_instances=1,
        )

        # 2. Daily at 08:30 local: check expiring social tokens (< 7 days)
        self._scheduler.add_job(
            self._tick_token_check,
            "cron",
            hour=8,
            minute=30,
            id="check_expiring_tokens",
            replace_existing=True,
        )

        # 3. Nightly at 02:30 local: SQLite backup + disk retention cleanup + low disk alert
        self._scheduler.add_job(
            self._tick_nightly_backup,
            "cron",
            hour=2,
            minute=30,
            id="nightly_backup_and_cleanup",
            replace_existing=True,
        )

        # 4. Daily report at schedule.daily_report_at (default 21:30)
        rep_h, rep_m = parse_hhmm(settings.schedule.daily_report_at, (21, 30))
        self._scheduler.add_job(
            self._tick_daily_report,
            "cron",
            hour=rep_h,
            minute=rep_m,
            id="daily_report",
            replace_existing=True,
        )

        # 5. Weekly report at schedule.weekly_report_at (default "MON 09:00")
        wk_dow, wk_h, wk_m = parse_dow_hhmm(settings.schedule.weekly_report_at, ("mon", 9, 0))
        self._scheduler.add_job(
            self._tick_weekly_report,
            "cron",
            day_of_week=wk_dow,
            hour=wk_h,
            minute=wk_m,
            id="weekly_report",
            replace_existing=True,
        )

        # 6. Hourly: collect due 24h / 72h / 7d post metrics + R2 & ticket maintenance
        self._scheduler.add_job(
            self._tick_collect_metrics,
            "interval",
            hours=1,
            id="collect_due_metrics",
            replace_existing=True,
            max_instances=1,
        )

        # 7. Daily trend scan at trends.scan_at (default 07:00, Phase 12 & 13)
        scan_h, scan_m = parse_hhmm(settings.trends.scan_at, (7, 0))
        self._scheduler.add_job(
            self._tick_trend_scan,
            "cron",
            hour=scan_h,
            minute=scan_m,
            id="daily_trend_scan",
            replace_existing=True,
        )

        # 8. Every 120s: scan inbox/ for manual tickets & flush deferred quiet-hour notifications
        self._scheduler.add_job(
            self._tick_inbox_and_deferred,
            "interval",
            seconds=120,
            id="inbox_and_deferred",
            replace_existing=True,
            max_instances=1,
        )

        self._scheduler.start()
        logger.info(
            "Started APScheduler (publish_due, token_check, nightly_backup, daily_report, weekly_report, collect_metrics, daily_trend_scan, inbox_and_deferred)"
        )

    async def _tick_publish_due(self) -> None:
        try:
            await asyncio.to_thread(publish_due_posts, self.paths)
        except Exception as exc:
            logger.error("Error in scheduled publish_due_posts tick: %s", exc)

    async def _tick_token_check(self) -> None:
        try:
            await asyncio.to_thread(check_expiring_tokens, self.paths)
        except Exception as exc:
            logger.error("Error in check_expiring_tokens tick: %s", exc)

    async def _tick_nightly_backup(self) -> None:
        try:
            await asyncio.to_thread(run_nightly_backup_and_cleanup, self.paths)
            await asyncio.to_thread(cleanup_staged_r2_objects, self.paths)
            await asyncio.to_thread(cleanup_expired_reference_videos, self.paths)
            await asyncio.to_thread(expire_stale_tickets, self.paths)
        except Exception as exc:
            logger.error("Error in nightly_backup_and_cleanup tick: %s", exc)

    async def _tick_daily_report(self) -> None:
        try:
            text = await asyncio.to_thread(daily_summary, self.paths)
            await asyncio.to_thread(send_text, self.paths, text, topic="reports")
        except Exception as exc:
            logger.error("Error in daily_report tick: %s", exc)

    async def _tick_weekly_report(self) -> None:
        try:
            text = await asyncio.to_thread(weekly_summary, self.paths)
            await asyncio.to_thread(send_text, self.paths, text, topic="reports")
        except Exception as exc:
            logger.error("Error in weekly_report tick: %s", exc)

    async def _tick_collect_metrics(self) -> None:
        try:
            await asyncio.to_thread(collect_due_metrics, self.paths)
            await asyncio.to_thread(cleanup_staged_r2_objects, self.paths)
            await asyncio.to_thread(expire_stale_tickets, self.paths)
        except Exception as exc:
            logger.error("Error in collect_due_metrics tick: %s", exc)

    async def _tick_trend_scan(self) -> None:
        try:
            await asyncio.to_thread(cleanup_expired_reference_videos, self.paths)
            await asyncio.to_thread(enqueue_job, self.paths.db_file, "scan_trends", ref_id=0)
        except Exception as exc:
            logger.error("Error in daily_trend_scan tick: %s", exc)

    async def _tick_inbox_and_deferred(self) -> None:
        try:
            await asyncio.to_thread(scan_inbox_for_tickets, self.paths)
            await asyncio.to_thread(flush_deferred_notifications, self.paths)
        except Exception as exc:
            logger.error("Error in inbox_and_deferred tick: %s", exc)

    def stop(self) -> None:
        if self._scheduler is not None and self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("Stopped APScheduler")
        self._scheduler = None

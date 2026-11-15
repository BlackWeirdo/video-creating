"""Telegram notifications for new footage and trend suggestions, and delivery of deferred ones."""
from __future__ import annotations

import asyncio

from videocreator.config import load_settings
from videocreator.db import get_conn, query_all, query_one
from videocreator.paths import AppPaths
from videocreator.secrets_store import SecretsStore
from videocreator.tg.approval_notify import notify_pending_async
from videocreator.tg.messages import build_new_footage_message, build_trend_suggestion_message
from videocreator.tg.quiet_hours import is_quiet_hours
from videocreator.tg.sender import send_text, send_text_async


def notify_new_footage(
    paths: AppPaths,
    footage_id: int,
    filename: str,
    shot_count: int,
) -> list[int]:
    """Sends Round 1 new footage notification with `3 bản` / `5 bản` / `Bỏ qua` buttons (`FR-FTG-09`, `FR-TG-11`)."""
    text, kb = build_new_footage_message(footage_id, filename, shot_count)
    return send_text(paths, text, keyboard=kb, respect_quiet_hours=True, topic="approvals")


async def send_open_suggestions_async(
    paths: AppPaths,
    *,
    statuses: tuple[str, ...] = ("new",),
    respect_quiet_hours: bool = True,
) -> int:
    """Sends trend suggestions still waiting for a decision (`FR-TG-10`) and marks new ones `sent`.

    Used after a scan, by `/trends`, and to deliver what quiet hours held back (`FR-TG-18`).
    """
    settings = load_settings(paths.config_file)
    marks = ",".join("?" for _ in statuses)
    rows = query_all(
        paths.db_file,
        f"SELECT * FROM suggestions WHERE status IN ({marks}) ORDER BY id ASC LIMIT ?",
        (*statuses, max(1, int(settings.telegram.max_trend_msgs_per_day))),
    )
    sent_count = 0
    for s_row in rows:
        t_row = (
            query_one(paths.db_file, "SELECT * FROM trend_items WHERE id = ?", (s_row["trend_item_id"],))
            if s_row.get("trend_item_id")
            else None
        )
        text, kb = build_trend_suggestion_message(s_row, t_row)
        sent = await send_text_async(
            paths, text, keyboard=kb, respect_quiet_hours=respect_quiet_hours, topic="trends"
        )
        if sent:
            sent_count += 1
            with get_conn(paths.db_file) as conn:
                conn.execute("UPDATE suggestions SET status = 'sent' WHERE id = ? AND status = 'new'", (s_row["id"],))
    return sent_count


def flush_deferred_notifications(paths: AppPaths) -> int:
    """Delivers what was held back (quiet hours, bot offline): finished videos never sent for approval
    and new trend suggestions (`FR-TG-18`). Called periodically from a worker thread."""
    settings = load_settings(paths.config_file)
    if not SecretsStore(paths.secrets_file).get("TELEGRAM_BOT_TOKEN") or not settings.telegram.allowed_chat_ids:
        return 0
    if is_quiet_hours(settings):
        return 0

    async def _flush() -> int:
        count = 0
        rows = query_all(
            paths.db_file,
            """
            SELECT id FROM videos
            WHERE status = 'pending_approval' AND tg_message_id IS NULL AND output_path IS NOT NULL
            ORDER BY id ASC LIMIT 10
            """,
        )
        for r in rows:
            if await notify_pending_async(paths, int(r["id"])):
                count += 1
        return count + await send_open_suggestions_async(paths)

    return asyncio.run(_flush())

"""Sends a finished video to Telegram for approval, with a 720p preview when the master is too large."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from videocreator.approval_queue import enrich_approval_video
from videocreator.config import load_settings
from videocreator.db import get_conn, query_all, query_one
from videocreator.paths import AppPaths
from videocreator.pipeline.ffmpeg import run_ffmpeg
from videocreator.posting.slots import default_target_account_ids, next_free_slot
from videocreator.products import product_name_map
from videocreator.secrets_store import SecretsStore
from videocreator.tg.messages import build_approval_message
from videocreator.tg.quiet_hours import is_quiet_hours
from videocreator.tg.sender import to_inline_markup
from videocreator.tg.topics import topic_thread_id

logger = logging.getLogger("videocreator.telegram")

MAX_TELEGRAM_VIDEO_MB = 45.0


def ensure_telegram_preview_video(
    paths: AppPaths,
    master_path: Path,
    video_id: int,
    *,
    max_mb: float = MAX_TELEGRAM_VIDEO_MB,
) -> Path:
    """Returns `master_path` if under `max_mb`, otherwise transcodes a 720p preview copy (`FR-APR-04`, `FR-TG-13`)."""
    size_mb = master_path.stat().st_size / (1024 * 1024)
    if size_mb <= max_mb:
        return master_path

    preview_path = paths.work_dir / f"tg_preview_720p_{video_id}.mp4"
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(
        [
            "-i",
            str(master_path.resolve()),
            "-vf",
            "scale=720:1280:force_original_aspect_ratio=decrease,pad=720:1280:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "26",
            "-c:a",
            "aac",
            "-b:a",
            "96k",
            str(preview_path.resolve()),
        ]
    )
    return preview_path


def _next_slot_label(paths: AppPaths, timezone_name: str, target_ids: set[int], video_id: int) -> str | None:
    """Local `dd/mm HH:MM` of the next free posting slot of the first target account."""
    if not target_ids:
        return None
    try:
        slot_utc = next_free_slot(paths.db_file, min(target_ids), config_file=paths.config_file)
        return slot_utc.astimezone(ZoneInfo(timezone_name or "Asia/Ho_Chi_Minh")).strftime("%d/%m %H:%M")
    except Exception as slot_exc:
        logger.debug("Could not compute next slot label for video #%d: %s", video_id, slot_exc)
        return None


async def _send_video_to_chats(
    paths: AppPaths,
    token: str,
    chat_ids: list[int],
    video_file: Path,
    caption: str,
    keyboard: Any,
    video_id: int,
) -> list[int]:
    """Sends the video to every allowed chat; a chat that fails is logged and skipped."""
    from telegram import Bot

    sent_ids: list[int] = []
    async with Bot(token=token) as bot:
        for chat_id in chat_ids:
            try:
                with video_file.open("rb") as vf:
                    msg = await bot.send_video(
                        chat_id=chat_id,
                        video=vf,
                        caption=caption,
                        reply_markup=keyboard,
                        message_thread_id=topic_thread_id(paths, int(chat_id), "approvals"),
                        read_timeout=120,
                        write_timeout=120,
                    )
                sent_ids.append(int(msg.message_id))
            except Exception as exc:
                logger.warning("Failed to send pending video #%d to chat %s: %s", video_id, chat_id, exc)
    return sent_ids


async def notify_pending_async(paths: AppPaths, video_id: int) -> list[int]:
    """Sends a `pending_approval` video with the 6-button Round 2 control keyboard (`FR-TG-13`)."""
    secrets = SecretsStore(paths.secrets_file)
    token = secrets.get("TELEGRAM_BOT_TOKEN")
    settings = load_settings(paths.config_file)
    if not token or not settings.telegram.allowed_chat_ids:
        return []
    if is_quiet_hours(settings):
        logger.info("Deferred pending_approval video #%d notification during quiet hours", video_id)
        return []

    row = query_one(paths.db_file, "SELECT * FROM videos WHERE id = ?", (video_id,))
    if row is None or not row.get("output_path"):
        return []

    master_path = paths.media_dir / str(row["output_path"])
    if not master_path.exists():
        return []

    product_map = product_name_map(paths.db_file)
    item = enrich_approval_video(paths.db_file, row, product_map)

    target_ids = set(default_target_account_ids(paths.db_file, video_id))
    acc_rows = query_all(
        paths.db_file,
        "SELECT id, name, platform FROM accounts WHERE enabled = 1 ORDER BY platform, id",
    )
    acc_names = [f"{a['name']} ({a['platform']})" for a in acc_rows if int(a["id"]) in target_ids]

    next_slot_str = _next_slot_label(paths, settings.schedule.timezone, target_ids, video_id)

    caption, kb_rows = build_approval_message(
        item, account_names=acc_names, next_slot_str=next_slot_str
    )
    video_to_send = ensure_telegram_preview_video(paths, master_path, video_id)
    keyboard = to_inline_markup(kb_rows)

    sent_ids = await _send_video_to_chats(
        paths, token, settings.telegram.allowed_chat_ids, video_to_send, caption, keyboard, video_id
    )

    if sent_ids:
        with get_conn(paths.db_file) as conn:
            conn.execute(
                "UPDATE videos SET tg_message_id = ? WHERE id = ?",
                (sent_ids[0], video_id),
            )
    return sent_ids


def notify_pending(paths: AppPaths, video_id: int) -> list[int]:
    """Triggers Telegram notification for `video_id` (no-op if bot token/chats are unset)."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(notify_pending_async(paths, video_id))
        return []
    except RuntimeError:
        return asyncio.run(notify_pending_async(paths, video_id))

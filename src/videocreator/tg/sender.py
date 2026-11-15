"""Sends text messages (with optional inline keyboard) to the allowed Telegram chats."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from videocreator.config import load_settings
from videocreator.paths import AppPaths
from videocreator.secrets_store import SecretsStore
from videocreator.tg.messages import KeyboardRows
from videocreator.tg.quiet_hours import is_quiet_hours
from videocreator.tg.topics import topic_thread_id

logger = logging.getLogger("videocreator.telegram")


def to_inline_markup(rows: KeyboardRows | None) -> Any:
    if not rows:
        return None
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(label, callback_data=cb_data) for label, cb_data in row]
            for row in rows
        ]
    )


async def send_text_async(
    paths: AppPaths,
    text: str,
    *,
    keyboard: KeyboardRows | None = None,
    respect_quiet_hours: bool = False,
    topic: str | None = None,
) -> list[int]:
    """Sends `text` (and optional inline keyboard) to all `allowed_chat_ids`, into `topic` where set up."""
    secrets = SecretsStore(paths.secrets_file)
    token = secrets.get("TELEGRAM_BOT_TOKEN")
    settings = load_settings(paths.config_file)
    if not token or not settings.telegram.allowed_chat_ids:
        return []
    if respect_quiet_hours and is_quiet_hours(settings):
        logger.info("Suppressed non-urgent Telegram message during quiet hours")
        return []

    from telegram import Bot

    markup = to_inline_markup(keyboard)
    msg_ids: list[int] = []
    async with Bot(token=token) as bot:
        for chat_id in settings.telegram.allowed_chat_ids:
            try:
                msg = await bot.send_message(
                    chat_id=chat_id,
                    text=text[:4096],
                    reply_markup=markup,
                    message_thread_id=topic_thread_id(paths, int(chat_id), topic),
                )
                msg_ids.append(int(msg.message_id))
            except Exception as exc:
                logger.warning("Failed to send Telegram message to chat %s: %s", chat_id, exc)
    return msg_ids


def send_text(
    paths: AppPaths,
    text: str,
    *,
    keyboard: KeyboardRows | None = None,
    respect_quiet_hours: bool = False,
    topic: str | None = None,
) -> list[int]:
    """Synchronous helper to send a Telegram alert/report message."""
    coro = send_text_async(
        paths, text, keyboard=keyboard, respect_quiet_hours=respect_quiet_hours, topic=topic
    )
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    loop.create_task(coro)
    return []

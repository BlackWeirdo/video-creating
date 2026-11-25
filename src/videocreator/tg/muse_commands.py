"""Telegram `/vid`, `/img`, `/voice` commands queueing Muse Gateway tasks & delivering media."""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from videocreator.config import load_settings
from videocreator.muse_gateway.store import create_muse_task
from videocreator.paths import AppPaths
from videocreator.secrets_store import SecretsStore
from videocreator.tg.access import TelegramAction
from videocreator.tg.approver_commands import CommandResult
from videocreator.tg.sender import send_text
from videocreator.tg.topics import topic_thread_id
from videocreator.workspaces import get_active_workspace_id

logger = logging.getLogger("videocreator.tg.muse_commands")

_DUR_TOKEN_RE = re.compile(r"^\[?(\d{1,2})s\]?$", re.IGNORECASE)
_RATIO_TOKEN_RE = re.compile(r"^\[?(9:16|16:9|1:1|4:3|3:4)\]?$")


def _parse_video_args(raw_args: str) -> tuple[str, int, str]:
    tokens = (raw_args or "").strip().split()
    duration = 8
    ratio = "9:16"
    kept: list[str] = []
    for tok in tokens:
        m_dur = _DUR_TOKEN_RE.match(tok)
        m_rat = _RATIO_TOKEN_RE.match(tok)
        if m_dur:
            duration = max(2, min(60, int(m_dur.group(1))))
        elif m_rat:
            ratio = m_rat.group(1)
        else:
            kept.append(tok)
    return " ".join(kept).strip(), duration, ratio


def cmd_muse_vid(action: TelegramAction, args: str) -> CommandResult:
    cfg = action.settings.muse_gateway
    if not cfg.enabled:
        return False, "Muse Gateway chưa được bật trong Cài đặt.", []
    prompt, dur, ratio = _parse_video_args(args)
    if not prompt:
        return False, "Cú pháp: /vid [8s] [9:16] <mô tả cảnh video>", []
    ws_id = get_active_workspace_id(action.paths.db_file)
    task = create_muse_task(
        action.paths.db_file,
        workspace_id=ws_id,
        kind="video",
        model=cfg.default_video_model or "muse-video",
        purpose="telegram",
        prompt=prompt,
        params={"duration": dur, "ratio": ratio},
        priority=10,
    )
    return (
        True,
        f"🎬 Đã xếp hàng tạo video Muse #{task['id']} ({dur}s, {ratio}). Hệ thống sẽ gửi file ngay khi xong.",
        [],
    )


def cmd_muse_img(action: TelegramAction, args: str) -> CommandResult:
    cfg = action.settings.muse_gateway
    if not cfg.enabled:
        return False, "Muse Gateway chưa được bật trong Cài đặt.", []
    prompt = (args or "").strip()
    if not prompt:
        return False, "Cú pháp: /img <mô tả hình ảnh>", []
    ws_id = get_active_workspace_id(action.paths.db_file)
    task = create_muse_task(
        action.paths.db_file,
        workspace_id=ws_id,
        kind="image",
        model=cfg.default_image_model or "muse-image",
        purpose="telegram",
        prompt=prompt,
        params={"ratio": "9:16", "count": 1},
        priority=10,
    )
    return True, f"🖼️ Đã xếp hàng tạo ảnh Muse #{task['id']}. Sẽ gửi ảnh khi hoàn tất.", []


def cmd_muse_voice(action: TelegramAction, args: str) -> CommandResult:
    cfg = action.settings.muse_gateway
    if not cfg.enabled:
        return False, "Muse Gateway chưa được bật trong Cài đặt.", []
    text = (args or "").strip()
    if not text:
        return False, "Cú pháp: /voice <nội dung cần đọc>", []
    ws_id = get_active_workspace_id(action.paths.db_file)
    task = create_muse_task(
        action.paths.db_file,
        workspace_id=ws_id,
        kind="audio",
        model="muse-voice",
        purpose="telegram",
        prompt=text,
        params={"voice": cfg.default_voice or "Glad Kite", "language": "vi"},
        priority=10,
    )
    return True, f"🎙️ Đã xếp hàng tạo giọng đọc Muse #{task['id']}.", []


async def _send_media_async(paths: AppPaths, task_row: dict[str, Any]) -> None:
    secrets = SecretsStore(paths.secrets_file)
    token = secrets.get("TELEGRAM_BOT_TOKEN")
    settings = load_settings(paths.config_file)
    if not token or not settings.telegram.allowed_chat_ids:
        return
    rel = str(task_row.get("local_path") or "")
    media_file = paths.media_dir / rel if rel else None
    if media_file is None or not media_file.is_file():
        return

    from telegram import Bot

    caption = f"✅ Muse #{task_row['id']} ({task_row['kind']}): {str(task_row['prompt'])[:180]}"
    async with Bot(token=token) as bot:
        for chat_id in settings.telegram.allowed_chat_ids:
            try:
                thread_id = topic_thread_id(paths, int(chat_id), None)
                with media_file.open("rb") as fh:
                    if task_row["kind"] == "video":
                        await bot.send_video(chat_id=chat_id, video=fh, caption=caption, message_thread_id=thread_id)
                    elif task_row["kind"] == "image":
                        await bot.send_photo(chat_id=chat_id, photo=fh, caption=caption, message_thread_id=thread_id)
                    else:
                        await bot.send_audio(chat_id=chat_id, audio=fh, caption=caption, message_thread_id=thread_id)
            except Exception as exc:
                logger.warning("Failed to send Muse media to Telegram chat %s: %s", chat_id, exc)


def notify_telegram_muse_result(paths: AppPaths, task_row: dict[str, Any]) -> None:
    if task_row["status"] != "succeeded":
        send_text(
            paths,
            f"❌ Muse #{task_row['id']} thất bại: {str(task_row.get('error') or 'Unknown error')[:250]}",
        )
        return
    coro = _send_media_async(paths, task_row)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(coro)
        return
    loop.create_task(coro)


__all__ = [
    "cmd_muse_img",
    "cmd_muse_vid",
    "cmd_muse_voice",
    "notify_telegram_muse_result",
]

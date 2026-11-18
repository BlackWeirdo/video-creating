"""Centralized Telegram callback router with single-point 2-layer allowlist and audit logging (Phase 16)."""
from __future__ import annotations

import logging
from datetime import datetime

from videocreator.config import load_settings
from videocreator.paths import AppPaths
from videocreator.tg.access import CallbackResult, TelegramAction, check_two_layer_allowlist
from videocreator.tg.callback_content import CONTENT_CALLBACKS
from videocreator.tg.callback_menus import MENU_CALLBACKS
from videocreator.tg.callback_video import VIDEO_CALLBACKS

logger = logging.getLogger("videocreator.tg.callbacks")

# `<prefix>:<id>[:<param>]` -> handler(action, id, parts)
ID_CALLBACKS = {**VIDEO_CALLBACKS, **MENU_CALLBACKS, **CONTENT_CALLBACKS}
UNSUPPORTED: CallbackResult = (False, "Hành động không hỗ trợ.", False, None)


def _run_menu_command(action: TelegramAction, command: str) -> CallbackResult:
    """`cmd:<name>`: a menu button runs the slash command of the same name."""
    from videocreator.tg.commands import execute_command

    ok, reply_text, keyboard = execute_command(
        action.paths,
        chat_id=action.chat_id,
        user_id=action.user_id,
        user_name=action.user_name,
        command=command,
        now_dt=action.now_dt,
    )
    return ok, reply_text, False, keyboard or None


def route_callback(
    paths: AppPaths,
    *,
    chat_id: int | None,
    user_id: int | None,
    user_name: str,
    data: str,
    now_dt: datetime | None = None,
) -> CallbackResult:
    """Routes any `<code_prefix>:<id>[:<param>]` callback after 2-layer allowlist verification.

    Returns `(allowed, message_text, state_changed, replacement_keyboard)`.
    """
    settings = load_settings(paths.config_file)
    clean_data = (data or "").strip()
    parts = clean_data.split(":")
    if len(parts) >= 2 and parts[0] == "cmd":
        action = TelegramAction(paths, settings, chat_id, user_id, user_name, now_dt)
        try:
            return _run_menu_command(action, parts[1])
        except Exception as exc:
            logger.warning("Error handling Telegram menu callback '%s': %s", clean_data, exc)
            return True, "Thao tác đã được xử lý hoặc không hợp lệ.", False, None

    allowed, err_msg = check_two_layer_allowlist(chat_id, user_id, settings)
    if not allowed:
        return False, err_msg or "Không có quyền.", False, None

    if len(parts) < 2:
        return False, "Dữ liệu nút không hợp lệ.", False, None

    prefix = parts[0]
    action = TelegramAction(paths, settings, chat_id, user_id, user_name, now_dt)
    try:
        handler = ID_CALLBACKS.get(prefix)
        if handler is None or not parts[1].isdigit():
            return UNSUPPORTED
        return handler(action, int(parts[1]), parts) or UNSUPPORTED
    except Exception as exc:
        logger.warning("Error handling Telegram callback '%s': %s", clean_data, exc)
        return True, "Thao tác đã được xử lý hoặc không hợp lệ.", False, None

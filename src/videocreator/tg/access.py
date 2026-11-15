"""Who may act through Telegram (2-layer allowlist, `FR-TG-01`) and how an action is attributed."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from videocreator.config import Settings
from videocreator.paths import AppPaths
from videocreator.tg.messages import KeyboardRows

logger = logging.getLogger("videocreator.tg.callbacks")

# Outcome of a button press: (allowed, message_text, state_changed, replacement_keyboard)
CallbackResult = tuple[bool, str, bool, KeyboardRows | None]


def check_two_layer_allowlist(
    chat_id: int | None,
    user_id: int | None,
    settings: Settings,
) -> tuple[bool, str | None]:
    """Single-point 2-layer allowlist check (`FR-TG-01`): verifies both `chat_id` and `user_id`."""
    if chat_id is None or int(chat_id) not in {int(c) for c in settings.telegram.allowed_chat_ids}:
        logger.warning("Blocked Telegram action from unauthorized chat_id=%s", chat_id)
        return False, "Chat này không nằm trong danh sách được phép."

    if settings.telegram.approver_user_ids:
        if user_id is None or int(user_id) not in {int(u) for u in settings.telegram.approver_user_ids}:
            logger.warning("Blocked Telegram action from non-approver user_id=%s", user_id)
            return False, "Tài khoản của bạn không có quyền thực hiện thao tác này."
    elif user_id is None:
        return False, "Thiếu thông tin người dùng."

    return True, None


def telegram_actor(user_id: int | None, user_name: str | None) -> str:
    """Audit-log actor of a Telegram user: `tg:<user_id>:<name>`."""
    return f"tg:{user_id}:{(user_name or '').strip() or user_id}"


@dataclass(frozen=True)
class TelegramAction:
    """One command or button press by an allowed Telegram user."""

    paths: AppPaths
    settings: Settings
    chat_id: int | None
    user_id: int | None
    user_name: str
    now_dt: datetime | None = None

    @property
    def actor(self) -> str:
        return telegram_actor(self.user_id, self.user_name)

    @property
    def display_user(self) -> str:
        return (self.user_name or "").strip() or str(self.user_id)

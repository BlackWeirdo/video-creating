"""Telegram forum topics: one topic per area, created by `/setup` (`FR-TG-02`)."""
from __future__ import annotations
import json
from typing import Any

from videocreator.db import get_setting, set_setting
from videocreator.jsonutil import loads_or
from videocreator.paths import AppPaths

TOPIC_NAMES = [
    ("trends", "Xu hướng"),
    ("approvals", "Chờ duyệt"),
    ("posted", "Đã đăng"),
    ("manual", "Việc tay"),
    ("alerts", "Lỗi và cảnh báo"),
    ("reports", "Báo cáo"),
]


TOPICS_SETTING_KEY = "tg_topics_json"


def topic_thread_id(paths: AppPaths, chat_id: int, topic: str | None) -> int | None:
    """Forum topic of `chat_id` created by `/setup` for `topic` (`FR-TG-02`); None sends to the general chat."""
    if not topic:
        return None
    try:
        saved = json.loads(get_setting(paths.db_file, TOPICS_SETTING_KEY) or "{}")
        if int(saved.get("chat_id") or 0) != int(chat_id):
            return None
        thread = (saved.get("threads") or {}).get(topic)
        return int(thread) if thread else None
    except (ValueError, TypeError, AttributeError):
        return None


async def setup_topics(paths: AppPaths, bot: Any, chat: Any) -> str:
    """`/setup` (`FR-TG-02`): creates one forum topic per area in a group with Topics enabled."""
    if not getattr(chat, "is_forum", False):
        set_setting(paths.db_file, TOPICS_SETTING_KEY, "{}")
        return "Nhóm này chưa bật Topics nên mọi tin được gửi chung. Bật Topics trong cài đặt nhóm, cho bot quyền quản lý chủ đề rồi chạy lại /setup."
    saved = loads_or(get_setting(paths.db_file, TOPICS_SETTING_KEY), {})
    threads: dict[str, int] = dict(saved.get("threads") or {}) if saved.get("chat_id") == chat.id else {}
    created: list[str] = []
    for key, label in TOPIC_NAMES:
        if key in threads:
            continue
        topic = await bot.create_forum_topic(chat_id=chat.id, name=label)
        threads[key] = int(topic.message_thread_id)
        created.append(label)
    set_setting(paths.db_file, TOPICS_SETTING_KEY, json.dumps({"chat_id": chat.id, "threads": threads}))
    if not created:
        return "Các Topic đã được tạo từ trước; không tạo thêm."
    return "🗂 Đã tạo Topic: " + ", ".join(created) + ". Từ giờ tin được gửi vào đúng Topic."

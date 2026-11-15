"""Telegram slash commands (Phase 16): `/link`, and the command table behind `execute_command`."""
from __future__ import annotations

import logging
from datetime import datetime

from videocreator.config import load_settings
from videocreator.paths import AppPaths
from videocreator.tg.access import TelegramAction, check_two_layer_allowlist
from videocreator.tg.approver_commands import APPROVER_COMMANDS, CommandHandler, CommandResult
from videocreator.tg.status_messages import build_menu_message, build_schedule_message, build_status_text

logger = logging.getLogger("videocreator.tg.commands")

BOT_COMMAND_SPECS: list[tuple[str, str]] = [
    ("menu", "Bàn phím các lệnh chính"),
    ("status", "Trạng thái hệ thống và chi phí AI hôm nay"),
    ("pending", "Gửi lại các video đang chờ duyệt"),
    ("schedule", "Lịch đăng hôm nay và ngày mai"),
    ("trends", "Gửi lại các đề xuất xu hướng chưa xử lý"),
    ("scan", "Quét xu hướng ngay"),
    ("link", "Thêm video tham khảo: /link <link Reel Facebook/Instagram>"),
    ("create", "Chọn trong 5 footage mới nhất để tạo video"),
    ("pause", "Tạm dừng đăng bài tự động"),
    ("resume", "Chạy lại đăng bài tự động"),
    ("report", "Báo cáo ngày (/report week cho báo cáo tuần)"),
    ("setup", "Tạo các Topic theo mảng trong nhóm"),
    ("help", "Danh sách lệnh điều khiển"),
]


# ---------- read-only commands (need `allowed_chat_ids` only) ----------

def _cmd_menu(action: TelegramAction, args: str) -> CommandResult:
    text, keyboard = build_menu_message()
    return True, text, keyboard


def _cmd_help(action: TelegramAction, args: str) -> CommandResult:
    lines = ["📖 DANH SÁCH LỆNH TELEGRAM:"]
    for name, description in BOT_COMMAND_SPECS:
        lines.append(f"• /{name} — {description}")
    return True, "\n".join(lines), []


def _cmd_status(action: TelegramAction, args: str) -> CommandResult:
    return True, build_status_text(action.paths.db_file, action.paths.config_file), []


def _cmd_schedule(action: TelegramAction, args: str) -> CommandResult:
    text, keyboard = build_schedule_message(action.paths.db_file, action.paths.config_file, now_dt=action.now_dt)
    return True, text, keyboard


def _cmd_report(action: TelegramAction, args: str) -> CommandResult:
    from videocreator.reports import daily_summary, weekly_summary

    if args.startswith("week"):
        return True, weekly_summary(action.paths, now_dt=action.now_dt), []
    return True, daily_summary(action.paths, now_dt=action.now_dt), []


# ---------- state-changing commands (need `approver_user_ids` too) ----------


READ_ONLY_COMMANDS: dict[str, CommandHandler] = {
    "menu": _cmd_menu,
    "help": _cmd_help,
    "status": _cmd_status,
    "schedule": _cmd_schedule,
    "report": _cmd_report,
}


def execute_command(
    paths: AppPaths,
    *,
    chat_id: int | None,
    user_id: int | None,
    user_name: str,
    command: str,
    args: str = "",
    now_dt: datetime | None = None,
) -> CommandResult:
    """Executes a Telegram slash command with 2-layer allowlist checks (`FR-TG-01`, `FR-TG-16`).

    Read-only commands (`/menu`, `/help`, `/status`, `/schedule`, `/report`) require `allowed_chat_ids`.
    State-mutating commands (`/scan`, `/create`, `/pause`, `/resume`, `/setup`, `/pending`, `/trends`)
    require both `allowed_chat_ids` and `approver_user_ids`.
    """
    settings = load_settings(paths.config_file)
    if chat_id is None or int(chat_id) not in {int(c) for c in settings.telegram.allowed_chat_ids}:
        logger.warning("Ignored command /%s from unauthorized chat_id=%s", command, chat_id)
        return False, "Chat này không nằm trong danh sách được phép.", []

    name = command.lstrip("/").split("@")[0].lower().strip()
    clean_args = (args or "").strip().lower()
    action = TelegramAction(paths, settings, chat_id, user_id, user_name, now_dt)

    read_only = READ_ONLY_COMMANDS.get(name)
    if read_only is not None:
        return read_only(action, clean_args)

    allowed, err_msg = check_two_layer_allowlist(chat_id, user_id, settings)
    if not allowed:
        return False, err_msg or "Không có quyền thực hiện lệnh này.", []
    approver_only = APPROVER_COMMANDS.get(name)
    if approver_only is None:
        return False, f"Lệnh không hỗ trợ: /{name}", []
    return approver_only(action, clean_args)

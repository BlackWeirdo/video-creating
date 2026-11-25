"""State-changing Telegram commands (need `approver_user_ids` as well as `allowed_chat_ids`)."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from videocreator.approval_queue import list_pending_approval_videos
from videocreator.db import get_conn, query_all, query_one, record_audit
from videocreator.jobs import enqueue_job
from videocreator.tg.access import TelegramAction
from videocreator.tg.messages import KeyboardRows, build_trend_suggestion_message

# (ok, reply_text, keyboard)
CommandResult = tuple[bool, str, KeyboardRows]


CommandHandler = Callable[[TelegramAction, str], CommandResult]


def _cmd_pause(action: TelegramAction, args: str) -> CommandResult:
    from videocreator.posting.service import set_posting_paused

    set_posting_paused(action.paths.db_file, True, actor=action.actor)
    return True, "⏸ Đã tạm dừng việc đăng bài tự động. Các bài đã xếp lịch được giữ nguyên.", []


def _cmd_resume(action: TelegramAction, args: str) -> CommandResult:
    from videocreator.posting.service import set_posting_paused

    set_posting_paused(action.paths.db_file, False, actor=action.actor)
    return True, "▶️ Đã chạy lại việc đăng bài tự động.", []


def _cmd_scan(action: TelegramAction, args: str) -> CommandResult:
    job_id = enqueue_job(action.paths.db_file, "trend_scan")
    with get_conn(action.paths.db_file) as conn:
        record_audit(
            conn,
            actor=action.actor,
            action="trends.scan_requested",
            object_type="job",
            object_id=job_id,
        )
    return True, f"🔍 Đã xếp hàng đợi quét xu hướng ngay (Job #{job_id}).", []


def _cmd_create(action: TelegramAction, args: str) -> CommandResult:
    rows = query_all(
        action.paths.db_file,
        """
        SELECT f.id, f.path, COUNT(s.id) AS shot_cnt
        FROM footage f
        LEFT JOIN shots s ON s.footage_id = f.id
        WHERE f.status = 'analysed'
        GROUP BY f.id
        ORDER BY f.id DESC
        LIMIT 5
        """,
    )
    if not rows:
        return True, "Hiện chưa có footage nào ở trạng thái đã phân tích (analysed).", []
    lines = ["🎬 Chọn footage trong 5 footage mới nhất để tạo video:"]
    keyboard: KeyboardRows = []
    for row in rows:
        footage_id = int(row["id"])
        lines.append(f"• #{footage_id} {Path(str(row['path'])).name} ({int(row['shot_cnt'] or 0)} shot)")
        keyboard.append(
            [
                (f"#{footage_id}: Tạo 3 bản", f"ftg_ok:{footage_id}:3"),
                (f"#{footage_id}: Tạo 5 bản", f"ftg_ok:{footage_id}:5"),
            ]
        )
    return True, "\n".join(lines), keyboard


def _cmd_trends(action: TelegramAction, args: str) -> CommandResult:
    newest = query_one(
        action.paths.db_file,
        """
        SELECT * FROM suggestions
        WHERE status IN ('new', 'sent')
        ORDER BY id DESC
        LIMIT 1
        """,
    )
    if newest is None:
        return True, "Hiện không có đề xuất xu hướng nào chưa xử lý.", []
    trend_item = (
        query_one(
            action.paths.db_file,
            "SELECT * FROM trend_items WHERE id = ?",
            (newest["trend_item_id"],),
        )
        if newest.get("trend_item_id")
        else None
    )
    text, keyboard = build_trend_suggestion_message(newest, trend_item)
    return True, text, keyboard


def _cmd_pending(action: TelegramAction, args: str) -> CommandResult:
    pending = list_pending_approval_videos(action.paths.db_file)
    if not pending:
        return True, "Hiện không có video nào đang chờ duyệt.", []
    ids_str = ", ".join(f"#{v['id']}" for v in pending)
    return True, f"⏳ Có {len(pending)} video đang chờ duyệt: {ids_str}", []


def _cmd_setup(action: TelegramAction, args: str) -> CommandResult:
    # Creating forum topics needs the Telegram API; the running bot handles `/setup` itself.
    return False, "Lệnh /setup chỉ chạy được khi gõ trong nhóm Telegram có bot.", []


def _cmd_muse_vid_proxy(action: TelegramAction, args: str) -> CommandResult:
    from videocreator.tg.muse_commands import cmd_muse_vid

    return cmd_muse_vid(action, args)


def _cmd_muse_img_proxy(action: TelegramAction, args: str) -> CommandResult:
    from videocreator.tg.muse_commands import cmd_muse_img

    return cmd_muse_img(action, args)


def _cmd_muse_voice_proxy(action: TelegramAction, args: str) -> CommandResult:
    from videocreator.tg.muse_commands import cmd_muse_voice

    return cmd_muse_voice(action, args)


APPROVER_COMMANDS: dict[str, CommandHandler] = {
    "pause": _cmd_pause,
    "resume": _cmd_resume,
    "scan": _cmd_scan,
    "create": _cmd_create,
    "trends": _cmd_trends,
    "pending": _cmd_pending,
    "setup": _cmd_setup,
    "vid": _cmd_muse_vid_proxy,
    "img": _cmd_muse_img_proxy,
    "voice": _cmd_muse_voice_proxy,
}

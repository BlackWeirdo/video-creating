"""Button actions on a video waiting for approval: approve, reject, redo, post now, accounts, captions."""
from __future__ import annotations


from videocreator.approvals import approve, post_now, reject
from videocreator.db import query_one
from videocreator.redo import redo_video
from videocreator.tg.access import CallbackResult, TelegramAction
from videocreator.tg.messages import KeyboardRows, build_approval_keyboard, build_post_now_confirm_keyboard
from videocreator.tg.pending_input import save_pending_input

ALREADY_HANDLED = "Video này đã được xử lý rồi."


def approve_video(action: TelegramAction, video_id: int, parts: list[str]) -> CallbackResult:
    """`ok:<vid>`"""
    db_file = action.paths.db_file
    won = approve(
        db_file,
        video_id,
        by=action.actor,
        config_file=action.paths.config_file,
        now_dt=action.now_dt,
    )
    if not won:
        return True, ALREADY_HANDLED, False, None
    n_posts = query_one(db_file, "SELECT COUNT(*) AS c FROM posts WHERE video_id = ?", (video_id,))
    if action.settings.schedule.auto and not int((n_posts or {}).get("c") or 0):
        return (
            True,
            f"✅ Đã duyệt bởi {action.display_user} (chưa xếp lịch: không có tài khoản đích phù hợp đang bật)",
            True,
            None,
        )
    return True, f"✅ Đã duyệt bởi {action.display_user}", True, None


def reject_video(action: TelegramAction, video_id: int, parts: list[str]) -> CallbackResult:
    """`no:<vid>` or `no_skip:<vid>`: reject without a reason."""
    if reject(action.paths.db_file, video_id, by=action.actor, reason="Loại qua Telegram"):
        return True, f"❌ Đã loại bởi {action.display_user}", True, None
    return True, ALREADY_HANDLED, False, None


def ask_reject_reason(action: TelegramAction, video_id: int, parts: list[str]) -> CallbackResult:
    """`no_ask:<vid>`: the next reply of this user is taken as the reject reason."""
    save_pending_input(
        action.paths.db_file,
        chat_id=int(action.chat_id or 0),
        user_id=int(action.user_id or 0),
        kind="reject_reason",
        ref_id=video_id,
        now_dt=action.now_dt,
    )
    keyboard: KeyboardRows = [[("Không cần lý do", f"no_skip:{video_id}"), ("↩ Quay lại", f"back:{video_id}")]]
    return (
        True,
        f"Hãy trả lời (reply) tin nhắn này để nhập lý do loại Video #{video_id}, hoặc bấm 'Không cần lý do'.",
        False,
        keyboard,
    )


def request_redo(action: TelegramAction, video_id: int, parts: list[str]) -> CallbackResult:
    """`redo:<vid>` (max 2 human redos)."""
    new_video_id = redo_video(
        action.paths.db_file, video_id, by=action.actor, is_auto_retry=False, max_retries=2
    )
    if new_video_id is None:
        return (
            True,
            "Không thể làm lại (đã đạt tối đa 2 lần Làm lại, video đã xử lý, hoặc là video Studio: sửa bằng prompt ở trang Studio).",
            False,
            None,
        )
    return (
        True,
        f"🔄 Đã yêu cầu làm lại bởi {action.display_user} -> đang lập kịch bản mới cho Video #{new_video_id}",
        True,
        None,
    )


def ask_post_now(action: TelegramAction, video_id: int, parts: list[str]) -> CallbackResult:
    """`now_ask:<vid>`: one confirmation step before publishing immediately."""
    return True, f"Xác nhận đăng ngay Video #{video_id}?", False, build_post_now_confirm_keyboard(video_id)


def confirm_post_now(action: TelegramAction, video_id: int, parts: list[str]) -> CallbackResult:
    """`now_yes:<vid>`"""
    post_ids = post_now(action.paths.db_file, video_id, by=action.actor, now_dt=action.now_dt)
    return True, f"🚀 Đã xếp đăng ngay bởi {action.display_user} ({len(post_ids)} tài khoản)", True, None


def cancel_post_now(action: TelegramAction, video_id: int, parts: list[str]) -> CallbackResult:
    """`now_cancel:<vid>`"""
    return True, "Đã huỷ thao tác đăng ngay.", False, build_approval_keyboard(video_id)


def back_to_main(action: TelegramAction, video_id: int, parts: list[str]) -> CallbackResult:
    """`back:<vid>`: from any sub-menu to the 6 main buttons."""
    return True, "Đã quay lại.", False, build_approval_keyboard(video_id)


VIDEO_CALLBACKS = {
    "ok": approve_video,
    "no": reject_video,
    "no_skip": reject_video,
    "no_ask": ask_reject_reason,
    "redo": request_redo,
    "now_ask": ask_post_now,
    "now_yes": confirm_post_now,
    "now_cancel": cancel_post_now,
    "back": back_to_main,
}

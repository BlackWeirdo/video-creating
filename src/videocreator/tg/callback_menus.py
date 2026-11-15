"""Sub-menus of a pending video: target accounts and caption editing."""
from __future__ import annotations

import json

from videocreator.db import get_conn, query_all, record_audit
from videocreator.posting.slots import default_target_account_ids
from videocreator.tg.access import CallbackResult, TelegramAction
from videocreator.tg.messages import KeyboardRows, build_account_toggle_keyboard, build_approval_keyboard
from videocreator.tg.pending_input import save_pending_input


def _enabled_accounts(action: TelegramAction) -> list[dict]:
    return query_all(
        action.paths.db_file,
        "SELECT id, platform, name FROM accounts WHERE enabled = 1 ORDER BY platform, id",
    )


def show_account_menu(action: TelegramAction, video_id: int, parts: list[str]) -> CallbackResult:
    """`acc_menu:<vid>`"""
    selected = set(default_target_account_ids(action.paths.db_file, video_id))
    keyboard = build_account_toggle_keyboard(video_id, _enabled_accounts(action), selected)
    return True, "Chọn tài khoản đích:", False, keyboard


def toggle_account(action: TelegramAction, video_id: int, parts: list[str]) -> CallbackResult | None:
    """`acc_tog:<vid>:<acc_id>`"""
    if len(parts) < 3 or not parts[2].isdigit():
        return None
    account_id = int(parts[2])
    selected = set(default_target_account_ids(action.paths.db_file, video_id))
    selected.symmetric_difference_update({account_id})
    with get_conn(action.paths.db_file) as conn:
        conn.execute(
            "UPDATE videos SET target_accounts_json = ? WHERE id = ?",
            (json.dumps(sorted(selected)), video_id),
        )
        record_audit(
            conn,
            actor=action.actor,
            action="video.accounts_toggled",
            object_type="video",
            object_id=video_id,
            detail=f"accounts={sorted(selected)}",
        )
    return (
        True,
        f"Đã cập nhật tài khoản đích ({len(selected)} tài khoản)",
        False,
        build_account_toggle_keyboard(video_id, _enabled_accounts(action), selected),
    )


def finish_account_menu(action: TelegramAction, video_id: int, parts: list[str]) -> CallbackResult:
    """`acc_done:<vid>`"""
    return True, f"Đã lưu danh sách tài khoản cho Video #{video_id}.", False, build_approval_keyboard(video_id)


def show_caption_menu(action: TelegramAction, video_id: int, parts: list[str]) -> CallbackResult:
    """`cap_menu:<vid>`"""
    keyboard: KeyboardRows = [
        [
            ("Facebook", f"cap_plat:{video_id}:facebook"),
            ("Instagram", f"cap_plat:{video_id}:instagram"),
        ],
        [
            ("Threads", f"cap_plat:{video_id}:threads"),
            ("TikTok", f"cap_plat:{video_id}:tiktok"),
        ],
        [("↩ Quay lại", f"back:{video_id}")],
    ]
    return True, "Chọn nền tảng cần sửa caption:", False, keyboard


def ask_new_caption(action: TelegramAction, video_id: int, parts: list[str]) -> CallbackResult | None:
    """`cap_plat:<vid>:<platform>`: the next reply of this user becomes that platform's caption."""
    if len(parts) < 3:
        return None
    platform = parts[2]
    save_pending_input(
        action.paths.db_file,
        chat_id=int(action.chat_id or 0),
        user_id=int(action.user_id or 0),
        kind=f"caption:{platform}",
        ref_id=video_id,
        now_dt=action.now_dt,
    )
    return (
        True,
        f"Hãy trả lời (reply) tin nhắn này bằng nội dung caption mới cho {platform.upper()} (Video #{video_id}).",
        False,
        build_approval_keyboard(video_id),
    )


MENU_CALLBACKS = {
    "acc_menu": show_account_menu,
    "acc_tog": toggle_account,
    "acc_done": finish_account_menu,
    "cap_menu": show_caption_menu,
    "cap_plat": ask_new_caption,
}

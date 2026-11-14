"""Centralized Telegram callback router with single-point 2-layer allowlist and audit logging (Phase 16)."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from videocreator.approvals import approve, post_now, redo_video, reject
from videocreator.config import Settings, load_settings
from videocreator.db import get_conn, query_all, query_one, record_audit
from videocreator.jobs import enqueue_job
from videocreator.paths import AppPaths
from videocreator.tg.messages import (
    KeyboardRows,
    build_account_toggle_keyboard,
    build_approval_keyboard,
    build_post_now_confirm_keyboard,
)

logger = logging.getLogger("videocreator.tg.callbacks")

PENDING_INPUT_TTL_MINUTES = 10


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


def save_pending_input(
    db_file: Path,
    *,
    chat_id: int,
    user_id: int,
    kind: str,
    ref_id: int,
    now_dt: datetime | None = None,
) -> None:
    """Stores pending reply input state in SQLite (`tg_pending_input`, 10-minute TTL, `FR-TG-21`)."""
    base_utc = (now_dt or datetime.now(timezone.utc)).astimezone(timezone.utc)
    exp_iso = (base_utc + timedelta(minutes=PENDING_INPUT_TTL_MINUTES)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    with get_conn(db_file) as conn:
        conn.execute(
            """
            INSERT INTO tg_pending_input (chat_id, user_id, kind, ref_id, expires_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(chat_id, user_id) DO UPDATE SET
                kind = excluded.kind,
                ref_id = excluded.ref_id,
                expires_at = excluded.expires_at
            """,
            (int(chat_id), int(user_id), kind, int(ref_id), exp_iso),
        )


def _get_selected_accounts_for_video(db_file: Path, video_id: int) -> set[int]:
    from videocreator.posting.slots import default_target_account_ids

    return set(default_target_account_ids(db_file, video_id))


def route_callback(
    paths: AppPaths,
    *,
    chat_id: int | None,
    user_id: int | None,
    user_name: str,
    data: str,
    now_dt: datetime | None = None,
) -> tuple[bool, str, bool, KeyboardRows | None]:
    """Routes any `<code_prefix>:<id>[:<param>]` callback after 2-layer allowlist verification.

    Returns `(allowed, message_text, state_changed, replacement_keyboard)`.
    """
    settings = load_settings(paths.config_file)
    allowed, err_msg = check_two_layer_allowlist(chat_id, user_id, settings)
    if not allowed:
        return False, err_msg or "Không có quyền.", False, None

    clean_data = (data or "").strip()
    parts = clean_data.split(":")
    if len(parts) < 2:
        return False, "Dữ liệu nút không hợp lệ.", False, None

    prefix = parts[0]
    actor = f"tg:{user_id}:{(user_name or '').strip() or user_id}"
    display_user = (user_name or "").strip() or str(user_id)

    try:
        from videocreator.api.routes_videos import save_plan_request_params
        from videocreator.posting.service import (
            cancel_scheduled_post,
            confirm_user_action_post,
            reschedule_post,
            retry_failed_post,
            utc_now_iso,
        )
        from videocreator.trends.suggest import accept_suggestion, dismiss_suggestion

        # 1. Approve (`ok:<vid>`)
        if prefix == "ok" and parts[1].isdigit():
            vid = int(parts[1])
            won = approve(
                paths.db_file,
                vid,
                by=actor,
                config_file=paths.config_file,
                now_dt=now_dt,
            )
            if won:
                n_posts = query_one(paths.db_file, "SELECT COUNT(*) AS c FROM posts WHERE video_id = ?", (vid,))
                if settings.schedule.auto and not int((n_posts or {}).get("c") or 0):
                    return True, f"✅ Đã duyệt bởi {display_user} (chưa xếp lịch: không có tài khoản đích phù hợp đang bật)", True, None
                return True, f"✅ Đã duyệt bởi {display_user}", True, None
            return True, "Video này đã được xử lý rồi.", False, None

        # 2. Reject directly (`no:<vid>` or `no_skip:<vid>`)
        if prefix in ("no", "no_skip") and parts[1].isdigit():
            vid = int(parts[1])
            won = reject(paths.db_file, vid, by=actor, reason="Loại qua Telegram")
            if won:
                return True, f"❌ Đã loại bởi {display_user}", True, None
            return True, "Video này đã được xử lý rồi.", False, None

        # 3. Ask for reject reason (`no_ask:<vid>`)
        if prefix == "no_ask" and parts[1].isdigit():
            vid = int(parts[1])
            save_pending_input(
                paths.db_file,
                chat_id=int(chat_id or 0),
                user_id=int(user_id or 0),
                kind="reject_reason",
                ref_id=vid,
                now_dt=now_dt,
            )
            kb: KeyboardRows = [[("Không cần lý do", f"no_skip:{vid}"), ("↩ Quay lại", f"back:{vid}")]]
            return True, f"Hãy trả lời (reply) tin nhắn này để nhập lý do loại Video #{vid}, hoặc bấm 'Không cần lý do'.", False, kb

        # 4. Redo video (`redo:<vid>`, max 2 human redos)
        if prefix == "redo" and parts[1].isdigit():
            vid = int(parts[1])
            new_vid = redo_video(
                paths.db_file, vid, by=actor, is_auto_retry=False, max_retries=2
            )
            if new_vid is not None:
                return (
                    True,
                    f"🔄 Đã yêu cầu làm lại bởi {display_user} -> đang lập kịch bản mới cho Video #{new_vid}",
                    True,
                    None,
                )
            return (
                True,
                "Không thể làm lại (đã đạt tối đa 2 lần Làm lại, video đã xử lý, hoặc là video Studio: sửa bằng prompt ở trang Studio).",
                False,
                None,
            )

        # 5. Post now confirmation step (`now_ask:<vid>`, `now_yes:<vid>`, `now_cancel:<vid>`)
        if prefix == "now_ask" and parts[1].isdigit():
            vid = int(parts[1])
            return (
                True,
                f"Xác nhận đăng ngay Video #{vid}?",
                False,
                build_post_now_confirm_keyboard(vid),
            )

        if prefix == "now_yes" and parts[1].isdigit():
            vid = int(parts[1])
            post_ids = post_now(paths.db_file, vid, by=actor, now_dt=now_dt)
            return (
                True,
                f"🚀 Đã xếp đăng ngay bởi {display_user} ({len(post_ids)} tài khoản)",
                True,
                None,
            )

        if prefix == "now_cancel" and parts[1].isdigit():
            return True, "Đã huỷ thao tác đăng ngay.", False, build_approval_keyboard(int(parts[1]))

        # Back from any sub-menu to the 6 main buttons (`back:<vid>`)
        if prefix == "back" and parts[1].isdigit():
            return True, "Đã quay lại.", False, build_approval_keyboard(int(parts[1]))

        # 6. Target account selection (`acc_menu:<vid>`, `acc_tog:<vid>:<acc_id>`, `acc_done:<vid>`)
        if prefix == "acc_menu" and parts[1].isdigit():
            vid = int(parts[1])
            accs = query_all(
                paths.db_file,
                "SELECT id, platform, name FROM accounts WHERE enabled = 1 ORDER BY platform, id",
            )
            sel = _get_selected_accounts_for_video(paths.db_file, vid)
            return (
                True,
                "Chọn tài khoản đích:",
                False,
                build_account_toggle_keyboard(vid, accs, sel),
            )

        if prefix == "acc_tog" and len(parts) >= 3 and parts[1].isdigit() and parts[2].isdigit():
            vid = int(parts[1])
            aid = int(parts[2])
            sel = _get_selected_accounts_for_video(paths.db_file, vid)
            if aid in sel:
                sel.remove(aid)
            else:
                sel.add(aid)
            with get_conn(paths.db_file) as conn:
                conn.execute(
                    "UPDATE videos SET target_accounts_json = ? WHERE id = ?",
                    (json.dumps(sorted(sel)), vid),
                )
                record_audit(
                    conn,
                    actor=actor,
                    action="video.accounts_toggled",
                    object_type="video",
                    object_id=vid,
                    detail=f"accounts={sorted(sel)}",
                )
            accs = query_all(
                paths.db_file,
                "SELECT id, platform, name FROM accounts WHERE enabled = 1 ORDER BY platform, id",
            )
            return (
                True,
                f"Đã cập nhật tài khoản đích ({len(sel)} tài khoản)",
                False,
                build_account_toggle_keyboard(vid, accs, sel),
            )

        if prefix == "acc_done" and parts[1].isdigit():
            vid = int(parts[1])
            return True, f"Đã lưu danh sách tài khoản cho Video #{vid}.", False, build_approval_keyboard(vid)

        # 7. Caption edit menu (`cap_menu:<vid>`, `cap_plat:<vid>:<platform>`)
        if prefix == "cap_menu" and parts[1].isdigit():
            vid = int(parts[1])
            kb_cap: KeyboardRows = [
                [
                    ("Facebook", f"cap_plat:{vid}:facebook"),
                    ("Instagram", f"cap_plat:{vid}:instagram"),
                ],
                [
                    ("Threads", f"cap_plat:{vid}:threads"),
                    ("TikTok", f"cap_plat:{vid}:tiktok"),
                ],
                [("↩ Quay lại", f"back:{vid}")],
            ]
            return True, "Chọn nền tảng cần sửa caption:", False, kb_cap

        if prefix == "cap_plat" and len(parts) >= 3 and parts[1].isdigit():
            vid = int(parts[1])
            plat = parts[2]
            save_pending_input(
                paths.db_file,
                chat_id=int(chat_id or 0),
                user_id=int(user_id or 0),
                kind=f"caption:{plat}",
                ref_id=vid,
                now_dt=now_dt,
            )
            return (
                True,
                f"Hãy trả lời (reply) tin nhắn này bằng nội dung caption mới cho {plat.upper()} (Video #{vid}).",
                False,
                build_approval_keyboard(vid),
            )

        # 8. Trend suggestion Round 1 (`sg_ok:<sid>[:<count>]`, `sg_no:<sid>`)
        if prefix == "sg_ok" and parts[1].isdigit():
            sid = int(parts[1])
            count = int(parts[2]) if len(parts) >= 3 and parts[2].isdigit() else 1
            job_id = accept_suggestion(
                paths, sid, count=count, auto_render=True, actor=actor
            )
            if job_id is not None:
                return (
                    True,
                    f"⚙️ Đang tạo {count} bản từ đề xuất #{sid}, bởi {display_user}",
                    True,
                    None,
                )
            return True, "Đề xuất này đã được xử lý rồi.", False, None

        if prefix == "sg_no" and parts[1].isdigit():
            sid = int(parts[1])
            won = dismiss_suggestion(paths.db_file, sid, actor=actor)
            if won:
                return True, f"Đã bỏ qua đề xuất #{sid} bởi {display_user}", True, None
            return True, "Đề xuất này đã được xử lý rồi.", False, None

        # 9. New footage Round 1 (`ftg_ok:<fid>:<count>`, `ftg_no:<fid>`)
        if prefix == "ftg_ok" and parts[1].isdigit():
            fid = int(parts[1])
            count = int(parts[2]) if len(parts) >= 3 and parts[2].isdigit() else 3
            save_plan_request_params(
                paths,
                fid,
                count=count,
                voice_lang=settings.telegram.default_voice_lang,
                caption_lang=settings.telegram.default_caption_lang,
                target_duration_s=15.0,
                auto_render=True,
            )
            enqueue_job(paths.db_file, "plan", ref_id=fid)
            with get_conn(paths.db_file) as conn:
                record_audit(
                    conn,
                    actor=actor,
                    action="footage.create_videos",
                    object_type="footage",
                    object_id=fid,
                    detail=f"count={count}, auto_render=True",
                )
            return (
                True,
                f"⚙️ Đang tạo {count} bản từ Footage #{fid}, bởi {display_user}",
                True,
                None,
            )

        if prefix == "ftg_no" and parts[1].isdigit():
            fid = int(parts[1])
            with get_conn(paths.db_file) as conn:
                record_audit(
                    conn,
                    actor=actor,
                    action="footage.skipped",
                    object_type="footage",
                    object_id=fid,
                )
            return True, f"Đã bỏ qua tạo tự động cho Footage #{fid}.", True, None

        # 10. Post schedule / retry / TikTok inbox confirmation (`retry:<pid>`, `posted:<pid>`, `pst_del:<pid>`, `pst_now:<pid>`)
        if prefix == "retry" and parts[1].isdigit():
            pid = int(parts[1])
            won = retry_failed_post(paths.db_file, pid, now_dt=now_dt, actor=actor)
            if won:
                return True, f"🔄 Đã xếp thử lại Post #{pid} bởi {display_user}", True, None
            return True, "Post này đã được xử lý rồi.", False, None

        if prefix == "posted" and parts[1].isdigit():
            pid = int(parts[1])
            won = confirm_user_action_post(paths.db_file, pid, actor=actor)
            if won:
                return True, f"✅ Đã xác nhận đăng Post #{pid} bởi {display_user}", True, None
            return True, "Post này đã được xác nhận trước đó.", False, None

        if prefix == "pst_del" and parts[1].isdigit():
            pid = int(parts[1])
            won = cancel_scheduled_post(paths.db_file, pid, actor=actor)
            if won:
                return True, f"🗑 Đã huỷ lịch Post #{pid} bởi {display_user}", True, None
            return True, "Không thể huỷ post này.", False, None

        if prefix == "pst_now" and parts[1].isdigit():
            pid = int(parts[1])
            won = reschedule_post(
                paths.db_file, pid, utc_now_iso(now_dt), actor=actor
            )
            if won:
                return True, f"🚀 Đã chuyển Post #{pid} sang đăng ngay bởi {display_user}", True, None
            return True, "Không thể đổi giờ post này.", False, None

        # 11. Menu command shortcuts (`cmd:<name>`)
        if prefix == "cmd" and len(parts) >= 2:
            from videocreator.tg.handlers import execute_command

            ok, reply_text, kb = execute_command(
                paths,
                chat_id=chat_id,
                user_id=user_id,
                user_name=user_name,
                command=parts[1],
                now_dt=now_dt,
            )
            return ok, reply_text, False, kb or None

        return False, "Hành động không hỗ trợ.", False, None
    except Exception as exc:
        logger.warning("Error handling Telegram callback '%s': %s", clean_data, exc)
        return True, "Thao tác đã được xử lý hoặc không hợp lệ.", False, None

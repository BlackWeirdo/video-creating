"""Button actions on trend suggestions, new footage, and scheduled posts."""
from __future__ import annotations

from videocreator.db import get_conn, record_audit
from videocreator.jobs import enqueue_job
from videocreator.posting.post_actions import (
    cancel_scheduled_post,
    confirm_user_action_post,
    reschedule_post,
    retry_failed_post,
)
from videocreator.tg.access import CallbackResult, TelegramAction
from videocreator.timeutil import utc_now_iso


def _count_param(parts: list[str], default: int) -> int:
    return int(parts[2]) if len(parts) >= 3 and parts[2].isdigit() else default


def accept_trend_suggestion(action: TelegramAction, suggestion_id: int, parts: list[str]) -> CallbackResult:
    """`sg_ok:<sid>[:<count>]`"""
    from videocreator.trends.suggestion_actions import accept_suggestion

    count = _count_param(parts, default=1)
    job_id = accept_suggestion(action.paths, suggestion_id, count=count, auto_render=True, actor=action.actor)
    if job_id is None:
        return True, "Đề xuất này đã được xử lý rồi.", False, None
    return True, f"⚙️ Đang tạo {count} bản từ đề xuất #{suggestion_id}, bởi {action.display_user}", True, None


def dismiss_trend_suggestion(action: TelegramAction, suggestion_id: int, parts: list[str]) -> CallbackResult:
    """`sg_no:<sid>`"""
    from videocreator.trends.suggestion_actions import dismiss_suggestion

    if dismiss_suggestion(action.paths.db_file, suggestion_id, actor=action.actor):
        return True, f"Đã bỏ qua đề xuất #{suggestion_id} bởi {action.display_user}", True, None
    return True, "Đề xuất này đã được xử lý rồi.", False, None


def create_videos_from_footage(action: TelegramAction, footage_id: int, parts: list[str]) -> CallbackResult:
    """`ftg_ok:<fid>:<count>`"""
    from videocreator.pipeline.plan_request import save_plan_request_params

    paths = action.paths
    count = _count_param(parts, default=3)
    save_plan_request_params(
        paths,
        footage_id,
        count=count,
        voice_lang=action.settings.telegram.default_voice_lang,
        caption_lang=action.settings.telegram.default_caption_lang,
        target_duration_s=15.0,
        auto_render=True,
    )
    enqueue_job(paths.db_file, "plan", ref_id=footage_id)
    with get_conn(paths.db_file) as conn:
        record_audit(
            conn,
            actor=action.actor,
            action="footage.create_videos",
            object_type="footage",
            object_id=footage_id,
            detail=f"count={count}, auto_render=True",
        )
    return True, f"⚙️ Đang tạo {count} bản từ Footage #{footage_id}, bởi {action.display_user}", True, None


def skip_footage(action: TelegramAction, footage_id: int, parts: list[str]) -> CallbackResult:
    """`ftg_no:<fid>`"""
    with get_conn(action.paths.db_file) as conn:
        record_audit(
            conn,
            actor=action.actor,
            action="footage.skipped",
            object_type="footage",
            object_id=footage_id,
        )
    return True, f"Đã bỏ qua tạo tự động cho Footage #{footage_id}.", True, None


def retry_post(action: TelegramAction, post_id: int, parts: list[str]) -> CallbackResult:
    """`retry:<pid>`"""
    if retry_failed_post(action.paths.db_file, post_id, now_dt=action.now_dt, actor=action.actor):
        return True, f"🔄 Đã xếp thử lại Post #{post_id} bởi {action.display_user}", True, None
    return True, "Post này đã được xử lý rồi.", False, None


def confirm_posted(action: TelegramAction, post_id: int, parts: list[str]) -> CallbackResult:
    """`posted:<pid>`: the user published the TikTok inbox draft by hand."""
    if confirm_user_action_post(action.paths.db_file, post_id, actor=action.actor):
        return True, f"✅ Đã xác nhận đăng Post #{post_id} bởi {action.display_user}", True, None
    return True, "Post này đã được xác nhận trước đó.", False, None


def cancel_post(action: TelegramAction, post_id: int, parts: list[str]) -> CallbackResult:
    """`pst_del:<pid>`"""
    if cancel_scheduled_post(action.paths.db_file, post_id, actor=action.actor):
        return True, f"🗑 Đã huỷ lịch Post #{post_id} bởi {action.display_user}", True, None
    return True, "Không thể huỷ post này.", False, None


def publish_post_now(action: TelegramAction, post_id: int, parts: list[str]) -> CallbackResult:
    """`pst_now:<pid>`"""
    if reschedule_post(action.paths.db_file, post_id, utc_now_iso(action.now_dt), actor=action.actor):
        return True, f"🚀 Đã chuyển Post #{post_id} sang đăng ngay bởi {action.display_user}", True, None
    return True, "Không thể đổi giờ post này.", False, None


CONTENT_CALLBACKS = {
    "sg_ok": accept_trend_suggestion,
    "sg_no": dismiss_trend_suggestion,
    "ftg_ok": create_videos_from_footage,
    "ftg_no": skip_footage,
    "retry": retry_post,
    "posted": confirm_posted,
    "pst_del": cancel_post,
    "pst_now": publish_post_now,
}

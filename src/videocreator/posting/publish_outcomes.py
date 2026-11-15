"""What happens to a post after a publish attempt: missed, retried with backoff, failed, or announced."""
from __future__ import annotations
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from videocreator.db import get_conn, query_one
from videocreator.paths import AppPaths
from videocreator.posting.base import PostResult
from videocreator.posting.captions import format_platform_caption
from videocreator.state_posts import recompute_video_status_from_posts, transition_post
from videocreator.tg.messages import KeyboardRows
from videocreator.tg.sender import send_text
from videocreator.timeutil import UTC_ISO_FORMAT, utc_now

BACKOFF_MINUTES: tuple[int, ...] = (1, 5, 30)
MAX_POST_ATTEMPTS = 3


def _append_error_hint(err_msg: str) -> str:
    lower = err_msg.lower()
    if "hướng dẫn:" in lower:
        return err_msg
    if "190" in lower or "token" in lower or "auth" in lower or "oauth" in lower:
        return f"{err_msg} (Hướng dẫn: Token hết hạn hoặc thiếu quyền — vào trang Tài khoản kết nối lại)"
    if "352" in lower or "preflight" in lower or "format" in lower or "codec" in lower:
        return f"{err_msg} (Hướng dẫn: Định dạng video không đạt chuẩn nền tảng — bấm Dựng lại bản master)"
    return err_msg


def compute_next_attempt_iso(attempts: int, now_dt: datetime | None = None) -> str:
    """Computes `next_attempt_at` ISO-8601 UTC timestamp for 1-based attempt number (`1 -> +1m`, `2 -> +5m`, `3 -> +30m`)."""
    base = utc_now(now_dt)
    idx = max(0, min(len(BACKOFF_MINUTES) - 1, int(attempts) - 1))
    delay_min = BACKOFF_MINUTES[idx]
    return (base + timedelta(minutes=delay_min)).strftime(UTC_ISO_FORMAT)


def _send_alert(paths: AppPaths, text: str, *, topic: str, keyboard: KeyboardRows | None = None) -> None:
    """Telegram notice about a post; a failed send never changes the outcome of publishing."""
    try:
        send_text(paths, text, keyboard=keyboard, topic=topic)
    except Exception:
        pass


def _retry_keyboard(post_id: int) -> KeyboardRows:
    return [[("🔄 Thử lại", f"retry:{post_id}")]]


def mark_missed(paths: AppPaths, post_row: dict[str, Any]) -> bool:
    """`FR-PST-09`: a post overdue by more than 6 hours is not auto-published; it is marked missed."""
    post_id = int(post_row["id"])
    if not transition_post(
        paths.db_file,
        post_id,
        "missed",
        expected_from="scheduled",
        error="missed: quá hạn hơn 6 giờ (máy chủ tắt hoặc tạm dừng)",
    ):
        return False
    _send_alert(
        paths,
        f"⚠️ Lỡ lịch đăng Video #{post_row['video_id']} trên {post_row['platform']} ({post_row['account_name']}), trễ hơn 6 giờ. Không tự đăng bù — bấm Thử lại nếu muốn đăng.",
        keyboard=_retry_keyboard(post_id),
        topic="alerts",
    )
    return True


def fail_post(db_file: Path, post_id: int, error: str) -> None:
    transition_post(db_file, post_id, "failed", expected_from="publishing", error=error)


def inbox_message_text(video_row: dict[str, Any] | None, post_row: dict[str, Any]) -> str:
    """Telegram text for a draft waiting in the app's inbox (`FR-PST-10`). The inbox API takes no
    caption, so the platform caption is included for the user to paste."""
    platform = str(post_row["platform"])
    text = (
        f"📥 Video #{post_row['video_id']} đã đẩy vào hộp nháp {platform} ({post_row['account_name']}). "
        f"Mở ứng dụng {platform}, vào hộp thư, dán caption bên dưới rồi bấm đăng, sau đó bấm 'Đã đăng'."
    )
    caption = format_platform_caption(video_row, platform) if video_row else ""
    if caption:
        text += f"\n\nCaption để dán:\n{caption}"
    return text


def notify_published(paths: AppPaths, post_row: dict[str, Any], result: PostResult) -> None:
    post_id = int(post_row["id"])
    video_id = int(post_row["video_id"])
    platform = str(post_row["platform"])
    if result.status == "needs_user_action":
        if platform == "tiktok":
            video_row = query_one(paths.db_file, "SELECT * FROM videos WHERE id = ?", (video_id,))
            text = inbox_message_text(video_row, post_row)
        else:
            text = (
                f"❓ Video #{video_id} có thể đã đăng lên {platform} ({post_row['account_name']}) ở lần thử trước "
                "nhưng app không tìm thấy bài. Mở trang để kiểm tra; nếu đã có bài thì bấm 'Đã đăng', "
                "nếu chưa có thì đăng tay rồi bấm 'Đã đăng'."
            )
        _send_alert(paths, text, keyboard=[[("✅ Đã đăng", f"posted:{post_id}")]], topic="posted")
        return
    _send_alert(
        paths,
        f"✅ Đã đăng Video #{video_id} lên {platform} ({post_row['account_name']}): {result.permalink or result.external_post_id}",
        topic="posted",
    )


def _set_attempts(db_file: Path, post_id: int, attempts: int) -> None:
    with get_conn(db_file) as conn:
        conn.execute("UPDATE posts SET attempts = ? WHERE id = ?", (attempts, post_id))


def handle_transient_failure(
    paths: AppPaths, post_row: dict[str, Any], exc: Exception, now_utc: datetime
) -> None:
    """Retries with backoff (`1m`, `5m`, `30m`); after the last attempt the post fails and the owner is told."""
    post_id = int(post_row["id"])
    video_id = int(post_row["video_id"])
    attempts = int(post_row.get("attempts") or 0) + 1
    err_msg = str(exc)[:500]
    if attempts < MAX_POST_ATTEMPTS:
        next_iso = compute_next_attempt_iso(attempts, now_dt=now_utc)
        with get_conn(paths.db_file) as conn:
            conn.execute(
                """
                UPDATE posts
                SET status = 'scheduled',
                    attempts = ?,
                    next_attempt_at = ?,
                    error = ?
                WHERE id = ?
                """,
                (attempts, next_iso, err_msg, post_id),
            )
            recompute_video_status_from_posts(conn, video_id)
        return
    _set_attempts(paths.db_file, post_id, attempts)
    fail_post(paths.db_file, post_id, f"Exhausted {attempts} attempts: {err_msg}")
    _send_alert(
        paths,
        f"❌ Đăng Video #{video_id} lên {post_row['platform']} thất bại sau {attempts} lần thử: {err_msg}",
        keyboard=_retry_keyboard(post_id),
        topic="alerts",
    )


def handle_permanent_failure(paths: AppPaths, post_row: dict[str, Any], exc: Exception) -> None:
    post_id = int(post_row["id"])
    attempts = int(post_row.get("attempts") or 0) + 1
    err_msg = _append_error_hint(str(exc)[:500])
    _set_attempts(paths.db_file, post_id, attempts)
    fail_post(paths.db_file, post_id, err_msg)
    _send_alert(
        paths,
        f"❌ Lỗi đăng Video #{post_row['video_id']} lên {post_row['platform']} ({post_row['account_name']}): {err_msg}",
        keyboard=_retry_keyboard(post_id),
        topic="alerts",
    )

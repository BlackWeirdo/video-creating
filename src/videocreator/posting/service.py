"""Posting orchestration service: scheduling, R2 staging, due-post publishing, and retry backoff (Phase 07)."""
from __future__ import annotations

import json
import logging
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from videocreator.db import get_conn, query_all, query_one, record_audit
from videocreator.paths import AppPaths
from videocreator.posting.base import PermanentPostError, Poster, TransientPostError
from videocreator.posting.facebook import FacebookPagePoster
from videocreator.posting.instagram import InstagramReelsPoster
from videocreator.posting.oauth import refresh_token_if_needed
from videocreator.posting.storage_r2 import delete_from_r2, upload_to_r2
from videocreator.posting.threads import ThreadsPoster
from videocreator.posting.tiktok import TikTokPoster
from videocreator.secrets_store import SecretsStore
from videocreator.state import recompute_video_status_from_posts, transition, transition_post
from videocreator.telegram_bot import send_text

logger = logging.getLogger("videocreator.posting.service")

BACKOFF_MINUTES: tuple[int, ...] = (1, 5, 30)
MAX_POST_ATTEMPTS = 3
MISSED_THRESHOLD_HOURS = 6


def is_posting_paused(db_file: Path) -> bool:
    row = query_one(
        db_file, "SELECT value FROM settings WHERE key = 'posting_paused'"
    )
    return bool(row and str(row["value"]).strip() in ("1", "true", "True"))


def set_posting_paused(
    db_file: Path, paused: bool, *, actor: str = "ui"
) -> None:
    val = "1" if paused else "0"
    with get_conn(db_file) as conn:
        conn.execute(
            """
            INSERT INTO settings (key, value) VALUES ('posting_paused', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (val,),
        )
        record_audit(
            conn,
            actor=actor,
            action="posting.paused" if paused else "posting.resumed",
            object_type="settings",
            object_id=None,
            detail=f"posting_paused={val}",
        )


def _parse_iso_utc(iso_str: str) -> datetime | None:
    try:
        clean = iso_str.strip()
        if clean.endswith("Z"):
            clean = clean[:-1] + "+00:00"
        dt = datetime.fromisoformat(clean)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _append_error_hint(err_msg: str) -> str:
    lower = err_msg.lower()
    if "190" in lower or "token" in lower or "auth" in lower or "oauth" in lower:
        if "hướng dẫn:" not in lower:
            return f"{err_msg} (Hướng dẫn: Token hết hạn hoặc thiếu quyền — vào trang Tài khoản kết nối lại)"
    if "352" in lower or "preflight" in lower or "format" in lower or "codec" in lower:
        if "hướng dẫn:" not in lower:
            return f"{err_msg} (Hướng dẫn: Định dạng video không đạt chuẩn nền tảng — bấm Dựng lại bản master)"
    return err_msg


def utc_now_iso(now_dt: datetime | None = None) -> str:
    dt = now_dt or datetime.now(timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def compute_next_attempt_iso(attempts: int, now_dt: datetime | None = None) -> str:
    """Computes `next_attempt_at` ISO-8601 UTC timestamp for 1-based attempt number (`1 -> +1m`, `2 -> +5m`, `3 -> +30m`)."""
    base = (now_dt or datetime.now(timezone.utc)).astimezone(timezone.utc)
    idx = max(0, min(len(BACKOFF_MINUTES) - 1, int(attempts) - 1))
    delay_min = BACKOFF_MINUTES[idx]
    return (base + timedelta(minutes=delay_min)).strftime("%Y-%m-%dT%H:%M:%SZ")


def format_platform_caption(video_row: dict[str, Any], platform: str) -> str:
    """Extracts the platform-specific caption text + hashtags from `videos.captions_json` or `plan_json`."""
    captions: dict[str, Any] = {}
    if video_row.get("captions_json"):
        try:
            captions = json.loads(str(video_row["captions_json"]))
        except Exception:
            captions = {}
    if not captions and video_row.get("plan_json"):
        try:
            captions = json.loads(str(video_row["plan_json"])).get("captions") or {}
        except Exception:
            captions = {}

    plat_obj = captions.get(platform) or {}
    text = str(plat_obj.get("text") or "").strip()
    tags = [str(t).strip() for t in (plat_obj.get("hashtags") or []) if str(t).strip()]
    if tags:
        return f"{text}\n\n{' '.join(tags)}".strip()
    return text


def schedule_approved_video(
    db_file: Path,
    video_id: int,
    *,
    account_ids: list[int],
    scheduled_at_iso: str | None = None,
    actor: str = "ui",
) -> list[int]:
    """Creates `posts` rows for an `approved` (or already `scheduled`) video and transitions video to `scheduled`."""
    v_row = query_one(db_file, "SELECT * FROM videos WHERE id = ?", (video_id,))
    if v_row is None:
        raise LookupError(f"Video #{video_id} not found")

    cur_status = str(v_row["status"])
    if cur_status not in ("approved", "scheduled"):
        raise ValueError(
            f"Video #{video_id} has status '{cur_status}'; only 'approved' videos can be scheduled/posted (FR-APR-01)"
        )

    clean_accs = sorted({int(a) for a in account_ids if int(a) > 0})
    if not clean_accs:
        raise ValueError("Must select at least one target account")

    sched_time = scheduled_at_iso or utc_now_iso()
    created_post_ids: list[int] = []

    with get_conn(db_file) as conn:
        for acc_id in clean_accs:
            acc_row = conn.execute(
                "SELECT id, enabled FROM accounts WHERE id = ?", (acc_id,)
            ).fetchone()
            if acc_row is None or not int(acc_row["enabled"]):
                continue
            cur = conn.execute(
                """
                INSERT INTO posts (video_id, account_id, status, scheduled_at)
                VALUES (?, ?, 'scheduled', ?)
                ON CONFLICT(video_id, account_id) DO NOTHING
                """,
                (video_id, acc_id, sched_time),
            )
            if cur.lastrowid and cur.rowcount == 1:
                created_post_ids.append(int(cur.lastrowid))

        if cur_status == "approved" and created_post_ids:
            transition(conn, video_id, "scheduled", expected_from="approved", actor=actor)
        record_audit(
            conn,
            actor=actor,
            action="video.scheduled",
            object_type="video",
            object_id=video_id,
            detail=f"accounts={clean_accs}, at={sched_time}",
        )

    return created_post_ids


def build_default_posters(
    paths: AppPaths, secrets_store: SecretsStore | None = None
) -> dict[str, Poster]:
    sec = secrets_store or SecretsStore(paths.secrets_file)
    return {
        "facebook": FacebookPagePoster(paths, sec),
        "instagram": InstagramReelsPoster(paths, sec),
        "threads": ThreadsPoster(paths, sec),
        "tiktok": TikTokPoster(paths, sec),
    }


def publish_due_posts(
    paths: AppPaths,
    *,
    poster_overrides: dict[str, Poster] | None = None,
    r2_uploader: Callable[[Path], tuple[str, str]] | None = None,
    now_dt: datetime | None = None,
) -> int:
    """Publishes all due `scheduled` posts (`scheduled_at <= now` and `next_attempt_at <= now`)."""
    if is_posting_paused(paths.db_file):
        return 0

    now_utc = (now_dt or datetime.now(timezone.utc)).astimezone(timezone.utc)
    now_str = utc_now_iso(now_utc)
    due_rows = query_all(
        paths.db_file,
        """
        SELECT p.*, a.platform, a.external_id, a.name AS account_name,
               a.secret_key, a.token_expires_at, a.enabled
        FROM posts p
        JOIN accounts a ON p.account_id = a.id
        WHERE p.status = 'scheduled'
          AND a.enabled = 1
          AND p.scheduled_at <= ?
          AND (p.next_attempt_at IS NULL OR p.next_attempt_at <= ?)
        ORDER BY p.scheduled_at ASC, p.id ASC
        """,
        (now_str, now_str),
    )
    if not due_rows:
        return 0

    posters = poster_overrides or build_default_posters(paths)
    staged_urls: dict[int, str] = {}
    processed_count = 0

    for post_row in due_rows:
        post_id = int(post_row["id"])
        video_id = int(post_row["video_id"])
        platform = str(post_row["platform"])

        # FR-PST-09: Post overdue > 6 hours -> do NOT auto-publish; mark missed and notify Telegram
        sched_dt = _parse_iso_utc(str(post_row.get("scheduled_at") or ""))
        if sched_dt is not None and (now_utc - sched_dt) > timedelta(hours=MISSED_THRESHOLD_HOURS):
            if transition_post(
                paths.db_file,
                post_id,
                "missed",
                expected_from="scheduled",
                error="missed: quá hạn hơn 6 giờ (máy chủ tắt hoặc tạm dừng)",
            ):
                processed_count += 1
                try:
                    send_text(
                        paths,
                        f"⚠️ Lỡ lịch đăng Video #{video_id} trên {platform} ({post_row['account_name']}), trễ hơn 6 giờ. Không tự đăng bù — bấm Thử lại nếu muốn đăng.",
                        keyboard=[[("🔄 Thử lại", f"retry:{post_id}")]],
                        topic="alerts",
                    )
                except Exception:
                    pass
            continue

        # Atomically claim the post by transitioning scheduled -> publishing
        if not transition_post(
            paths.db_file, post_id, "publishing", expected_from="scheduled"
        ):
            continue

        processed_count += 1
        video_row = query_one(paths.db_file, "SELECT * FROM videos WHERE id = ?", (video_id,))
        if video_row is None or not video_row.get("output_path"):
            transition_post(
                paths.db_file,
                post_id,
                "failed",
                expected_from="publishing",
                error="Missing rendered output video",
            )
            continue

        video_path = paths.media_dir / str(video_row["output_path"])
        caption = format_platform_caption(video_row, platform)
        poster = posters.get(platform)
        if poster is None:
            transition_post(
                paths.db_file,
                post_id,
                "failed",
                expected_from="publishing",
                error=f"No poster adapter registered for platform '{platform}'",
            )
            continue

        try:
            try:
                refresh_token_if_needed(paths, post_row, now_dt=now_utc)
            except Exception as ref_exc:
                logger.warning("Token refresh check failed for account %s: %s", post_row.get("account_id"), ref_exc)

            # FR-PST-05: one R2 upload per video, reused by every account and every retry.
            if platform != "tiktok" and video_id not in staged_urls:
                if video_row.get("r2_url"):
                    staged_urls[video_id] = str(video_row["r2_url"])
                else:
                    if r2_uploader is not None:
                        obj_key, pub_url = r2_uploader(video_path)
                    else:
                        obj_key, pub_url = upload_to_r2(paths, video_path)
                    with get_conn(paths.db_file) as conn:
                        conn.execute(
                            "UPDATE videos SET r2_key = ?, r2_url = ? WHERE id = ?", (obj_key, pub_url, video_id)
                        )
                    staged_urls[video_id] = pub_url
            video_url = staged_urls.get(video_id, "")

            res = poster.publish(
                account=post_row,
                video_url=video_url,
                video_path=video_path,
                caption=caption,
                post=post_row,
            )
            transition_post(
                paths.db_file,
                post_id,
                res.status,
                expected_from="publishing",
                external_post_id=res.external_post_id,
                permalink=res.permalink,
                error=None,
                posted_at=utc_now_iso(now_utc) if res.status == "posted" else None,
            )
            try:
                if res.status == "needs_user_action":
                    send_text(
                        paths,
                        f"📥 Video #{video_id} đã đẩy vào hộp nháp {platform} ({post_row['account_name']}). Mở ứng dụng {platform}, vào hộp thư và bấm đăng, sau đó bấm 'Đã đăng'.",
                        keyboard=[[("✅ Đã đăng", f"posted:{post_id}")]],
                        topic="posted",
                    )
                else:
                    send_text(
                        paths,
                        f"✅ Đã đăng Video #{video_id} lên {platform} ({post_row['account_name']}): {res.permalink or res.external_post_id}",
                        topic="posted",
                    )
            except Exception:
                pass

        except TransientPostError as exc:
            attempts = int(post_row.get("attempts") or 0) + 1
            err_msg = str(exc)[:500]
            if attempts >= MAX_POST_ATTEMPTS:
                with get_conn(paths.db_file) as conn:
                    conn.execute(
                        "UPDATE posts SET attempts = ? WHERE id = ?",
                        (attempts, post_id),
                    )
                transition_post(
                    paths.db_file,
                    post_id,
                    "failed",
                    expected_from="publishing",
                    error=f"Exhausted {attempts} attempts: {err_msg}",
                )
                try:
                    send_text(
                        paths,
                        f"❌ Đăng Video #{video_id} lên {platform} thất bại sau {attempts} lần thử: {err_msg}",
                        keyboard=[[("🔄 Thử lại", f"retry:{post_id}")]],
                        topic="alerts",
                    )
                except Exception:
                    pass
            else:
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

        except (PermanentPostError, Exception) as exc:
            attempts = int(post_row.get("attempts") or 0) + 1
            err_msg = _append_error_hint(str(exc)[:500])
            with get_conn(paths.db_file) as conn:
                conn.execute(
                    "UPDATE posts SET attempts = ? WHERE id = ?",
                    (attempts, post_id),
                )
            transition_post(
                paths.db_file,
                post_id,
                "failed",
                expected_from="publishing",
                error=err_msg,
            )
            try:
                send_text(
                    paths,
                    f"❌ Lỗi đăng Video #{video_id} lên {platform} ({post_row['account_name']}): {err_msg}",
                    keyboard=[[("🔄 Thử lại", f"retry:{post_id}")]],
                    topic="alerts",
                )
            except Exception:
                pass

    return processed_count


def cleanup_staged_r2_objects(
    paths: AppPaths,
    *,
    now_dt: datetime | None = None,
    deleter: Callable[[str], bool] | None = None,
) -> int:
    """Deletes the public R2 copy of a video 24 hours after all its posts reached a final state (`FR-PST-05`)."""
    cutoff = utc_now_iso((now_dt or datetime.now(timezone.utc)) - timedelta(hours=24))
    rows = query_all(
        paths.db_file,
        """
        SELECT v.id, v.r2_key
        FROM videos v
        WHERE v.r2_key IS NOT NULL AND v.r2_key != ''
          AND NOT EXISTS (
              SELECT 1 FROM posts p WHERE p.video_id = v.id AND p.status IN ('scheduled', 'publishing')
          )
          AND COALESCE(
              (SELECT MAX(COALESCE(p.posted_at, p.next_attempt_at, p.scheduled_at)) FROM posts p WHERE p.video_id = v.id),
              v.created_at
          ) < ?
        """,
        (cutoff,),
    )
    delete = deleter or (lambda key: delete_from_r2(paths, key))
    deleted = 0
    for r in rows:
        if delete(str(r["r2_key"])):
            with get_conn(paths.db_file) as conn:
                conn.execute("UPDATE videos SET r2_key = NULL, r2_url = NULL WHERE id = ?", (int(r["id"]),))
            deleted += 1
    return deleted


def retry_failed_post(
    db_file: Path,
    post_id: int,
    *,
    scheduled_at_iso: str | None = None,
    now_dt: datetime | None = None,
    actor: str = "ui",
) -> bool:
    """Resets a `failed` or `missed` post back to `scheduled` (`attempts=0`, `next_attempt_at=NULL`)."""
    p_row = query_one(
        db_file, "SELECT id, video_id, status FROM posts WHERE id = ?", (post_id,)
    )
    if p_row is None:
        raise LookupError(f"Post #{post_id} not found")
    cur_status = str(p_row["status"])
    if cur_status not in ("failed", "missed"):
        return False

    new_sched = scheduled_at_iso or utc_now_iso(now_dt)
    video_id = int(p_row["video_id"])
    with get_conn(db_file) as conn:
        if not transition_post(conn, post_id, "scheduled", expected_from=cur_status):
            return False
        conn.execute(
            """
            UPDATE posts
            SET scheduled_at = ?,
                attempts = 0,
                next_attempt_at = NULL,
                error = NULL
            WHERE id = ?
            """,
            (new_sched, post_id),
        )
        recompute_video_status_from_posts(conn, video_id)
        record_audit(
            conn,
            actor=actor,
            action="post.retried",
            object_type="post",
            object_id=post_id,
            detail=f"from={cur_status}, at={new_sched}",
        )
    return True


def reschedule_post(
    db_file: Path,
    post_id: int,
    scheduled_at_iso: str,
    *,
    actor: str = "ui",
) -> bool:
    """Updates `scheduled_at` of an unposted (`scheduled` / `failed` / `missed`) post."""
    p_row = query_one(
        db_file, "SELECT id, video_id, status FROM posts WHERE id = ?", (post_id,)
    )
    if p_row is None:
        raise LookupError(f"Post #{post_id} not found")
    cur_status = str(p_row["status"])
    if cur_status not in ("scheduled", "failed", "missed"):
        return False

    video_id = int(p_row["video_id"])
    with get_conn(db_file) as conn:
        conn.execute(
            """
            UPDATE posts
            SET status = 'scheduled',
                scheduled_at = ?,
                attempts = 0,
                next_attempt_at = NULL,
                error = NULL
            WHERE id = ?
            """,
            (scheduled_at_iso, post_id),
        )
        recompute_video_status_from_posts(conn, video_id)
        record_audit(
            conn,
            actor=actor,
            action="post.rescheduled",
            object_type="post",
            object_id=post_id,
            detail=f"at={scheduled_at_iso}",
        )
    return True


def cancel_scheduled_post(
    db_file: Path,
    post_id: int,
    *,
    actor: str = "ui",
) -> bool:
    """Deletes an unposted `scheduled` / `missed` / `failed` post; if no posts remain for the video, returns video to `approved`."""
    p_row = query_one(
        db_file, "SELECT id, video_id, status FROM posts WHERE id = ?", (post_id,)
    )
    if p_row is None:
        raise LookupError(f"Post #{post_id} not found")
    if str(p_row["status"]) in ("publishing", "posted"):
        return False

    video_id = int(p_row["video_id"])
    with get_conn(db_file) as conn:
        conn.execute("DELETE FROM posts WHERE id = ?", (post_id,))
        rem = conn.execute(
            "SELECT COUNT(*) AS c FROM posts WHERE video_id = ?", (video_id,)
        ).fetchone()
        if rem is not None and int(rem["c"]) == 0:
            conn.execute(
                "UPDATE videos SET status = 'approved' WHERE id = ? AND status IN ('scheduled', 'failed')",
                (video_id,),
            )
        else:
            recompute_video_status_from_posts(conn, video_id)
        record_audit(
            conn,
            actor=actor,
            action="post.cancelled",
            object_type="post",
            object_id=post_id,
            detail=f"video_id={video_id}",
        )
    return True


def confirm_user_action_post(
    db_file: Path,
    post_id: int,
    *,
    external_post_id: str | None = None,
    permalink: str | None = None,
    actor: str = "ui",
) -> bool:
    """Marks a `needs_user_action` post (e.g. TikTok inbox) as `posted` after user confirmation."""
    p_row = query_one(
        db_file, "SELECT id, status FROM posts WHERE id = ?", (post_id,)
    )
    if p_row is None:
        raise LookupError(f"Post #{post_id} not found")
    if str(p_row["status"]) != "needs_user_action":
        return False
    won = transition_post(
        db_file,
        post_id,
        "posted",
        expected_from="needs_user_action",
        external_post_id=external_post_id,
        permalink=permalink,
    )
    if won:
        with get_conn(db_file) as conn:
            record_audit(
                conn,
                actor=actor,
                action="post.confirmed_posted",
                object_type="post",
                object_id=post_id,
                detail=permalink or external_post_id,
            )
    return won


def build_manual_bundle_zip(paths: AppPaths, video_id: int) -> Path:
    """Builds a downloadable `.zip` containing the rendered MP4, cover image, and 4 platform captions."""
    v_row = query_one(paths.db_file, "SELECT * FROM videos WHERE id = ?", (video_id,))
    if v_row is None or not v_row.get("output_path"):
        raise LookupError(f"Rendered video #{video_id} not found")

    mp4_path = paths.media_dir / str(v_row["output_path"])
    if not mp4_path.exists():
        raise FileNotFoundError(f"Video file not found on disk: {mp4_path}")

    zip_path = paths.work_dir / f"manual_bundle_video_{video_id}.zip"
    zip_path.parent.mkdir(parents=True, exist_ok=True)

    caption_lines = [f"=== PACK ĐĂNG TAY VIDEO #{video_id} ===", ""]
    for plat in ("facebook", "instagram", "threads", "tiktok"):
        caption_lines.append(f"--- {plat.upper()} ---")
        caption_lines.append(format_platform_caption(v_row, plat))
        caption_lines.append("")

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(mp4_path, arcname=f"video_{video_id}.mp4")
        if v_row.get("cover_path"):
            cov = paths.media_dir / str(v_row["cover_path"])
            if cov.exists():
                zf.write(cov, arcname=f"cover_{video_id}.jpg")
        zf.writestr("captions.txt", "\n".join(caption_lines))

    return zip_path

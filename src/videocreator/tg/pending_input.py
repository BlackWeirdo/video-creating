"""Stateful reply input (`tg_pending_input`, `FR-TG-21`): a button asks, the user's next reply answers."""
from __future__ import annotations
import json
from datetime import datetime, timedelta
from pathlib import Path

from videocreator.approvals import reject
from videocreator.config import Settings, load_settings
from videocreator.db import get_conn, get_write_conn, query_one, record_audit
from videocreator.jsonutil import loads_or
from videocreator.paths import AppPaths
from videocreator.tg.access import check_two_layer_allowlist, telegram_actor
from videocreator.timeutil import UTC_ISO_FORMAT, utc_now

PENDING_INPUT_TTL_MINUTES = 10
DEFAULT_MAX_CAPTION_CHARS = 2200


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
    base_utc = utc_now(now_dt)
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


def _reject_with_reason(db_file: Path, video_id: int, reason: str, actor: str) -> str:
    safe_reason = reason[:300]
    if reject(db_file, video_id, by=actor, reason=safe_reason):
        return f"❌ Đã loại Video #{video_id} (Lý do: {safe_reason})"
    return f"Video #{video_id} đã được xử lý trước đó."


def _update_caption(
    db_file: Path, settings: Settings, video_id: int, platform: str, new_text: str, actor: str
) -> str:
    max_chars = DEFAULT_MAX_CAPTION_CHARS
    if platform in settings.platform_limits:
        max_chars = int(settings.platform_limits[platform].max_caption_chars)
    truncated = new_text[:max_chars]

    with get_write_conn(db_file) as conn:
        video_row = conn.execute(
            "SELECT plan_json, captions_json FROM videos WHERE id = ?",
            (video_id,),
        ).fetchone()
        if video_row is None:
            return f"Không tìm thấy Video #{video_id}."

        raw_plan = video_row["plan_json"]
        plan = loads_or(raw_plan, {})
        base_caps = plan.get("captions") if isinstance(plan, dict) and isinstance(plan.get("captions"), dict) else {}
        override_caps = loads_or(video_row["captions_json"], {})
        if not isinstance(override_caps, dict):
            override_caps = {}
        captions = {k: (dict(v) if isinstance(v, dict) else v) for k, v in {**base_caps, **override_caps}.items()}

        if isinstance(captions.get(platform), dict):
            captions[platform]["text"] = truncated
        else:
            captions[platform] = {"text": truncated, "hashtags": []}

        if raw_plan and isinstance(plan, dict):
            plan["captions"] = captions
            conn.execute(
                "UPDATE videos SET plan_json = ?, captions_json = ? WHERE id = ?",
                (
                    json.dumps(plan, ensure_ascii=False),
                    json.dumps(captions, ensure_ascii=False),
                    video_id,
                ),
            )
        else:
            conn.execute(
                "UPDATE videos SET captions_json = ? WHERE id = ?",
                (json.dumps(captions, ensure_ascii=False), video_id),
            )
        record_audit(
            conn,
            actor=actor,
            action="video.caption_updated",
            object_type="video",
            object_id=video_id,
            detail=f"platform={platform}, len={len(truncated)}",
        )
    return f"✏️ Đã cập nhật caption {platform.upper()} cho Video #{video_id} ({len(truncated)} ký tự)."


def handle_pending_reply_input(
    paths: AppPaths,
    *,
    chat_id: int | None,
    user_id: int | None,
    user_name: str,
    text: str,
    now_dt: datetime | None = None,
) -> tuple[bool, str | None]:
    """Processes a user reply when `tg_pending_input` has an active non-expired entry (`FR-TG-21`).

    Supports:
    - `kind == 'reject_reason'`: calls `reject(db_file, ref_id, by=actor, reason=...)`
    - `kind == 'caption:<platform>'`: updates `videos.captions_json` for `<platform>` (truncated to platform limit)
    """
    if chat_id is None or user_id is None:
        return False, None

    settings = load_settings(paths.config_file)
    allowed, _ = check_two_layer_allowlist(chat_id, user_id, settings)
    if not allowed:
        return False, None

    row = query_one(
        paths.db_file,
        "SELECT * FROM tg_pending_input WHERE chat_id = ? AND user_id = ?",
        (int(chat_id), int(user_id)),
    )
    if row is None:
        return False, None

    base_utc = utc_now(now_dt)
    now_iso = base_utc.strftime(UTC_ISO_FORMAT)

    with get_conn(paths.db_file) as conn:
        conn.execute(
            "DELETE FROM tg_pending_input WHERE chat_id = ? AND user_id = ?",
            (int(chat_id), int(user_id)),
        )

    if str(row["expires_at"]) < now_iso:
        return False, "Phiên nhập thông tin đã hết hạn (quá 10 phút). Vui lòng bấm lại nút trên tin nhắn."

    kind = str(row["kind"])
    ref_id = int(row["ref_id"])
    clean_text = (text or "").strip()
    if not clean_text:
        return False, None

    actor = telegram_actor(user_id, user_name)
    if kind == "reject_reason":
        return True, _reject_with_reason(paths.db_file, ref_id, clean_text, actor)
    if kind.startswith("caption:"):
        platform = kind.split(":", 1)[1].strip().lower()
        return True, _update_caption(paths.db_file, settings, ref_id, platform, clean_text, actor)
    return False, None

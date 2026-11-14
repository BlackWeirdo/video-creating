"""Telegram command handlers, stateful reply input (`tg_pending_input`), Topics setup, and Presets (Phase 16)."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from videocreator.approvals import list_pending_approval_videos, reject
from videocreator.config import load_settings
from videocreator.db import get_conn, get_setting, query_all, query_one, record_audit
from videocreator.jobs import enqueue_job
from videocreator.paths import AppPaths
from videocreator.tg.callbacks import check_two_layer_allowlist
from videocreator.tg.messages import (
    KeyboardRows,
    build_menu_message,
    build_new_footage_message,
    build_schedule_message,
    build_trend_suggestion_message,
)

logger = logging.getLogger("videocreator.tg.handlers")

TOPIC_NAMES = [
    ("trends", "Xu hướng"),
    ("approvals", "Chờ duyệt"),
    ("posted", "Đã đăng"),
    ("manual", "Việc tay"),
    ("alerts", "Lỗi và cảnh báo"),
    ("reports", "Báo cáo"),
]

BOT_COMMAND_SPECS: list[tuple[str, str]] = [
    ("menu", "Bàn phím các lệnh chính"),
    ("status", "Trạng thái hệ thống và chi phí AI hôm nay"),
    ("pending", "Gửi lại các video đang chờ duyệt"),
    ("schedule", "Lịch đăng hôm nay và ngày mai"),
    ("trends", "Gửi lại các đề xuất xu hướng chưa xử lý"),
    ("scan", "Quét xu hướng ngay"),
    ("create", "Chọn trong 5 footage mới nhất để tạo video"),
    ("pause", "Tạm dừng đăng bài tự động"),
    ("resume", "Chạy lại đăng bài tự động"),
    ("report", "Báo cáo ngày (/report week cho báo cáo tuần)"),
    ("setup", "Tạo các Topic theo mảng trong nhóm"),
    ("help", "Danh sách lệnh điều khiển"),
]


def build_status_text(db_file: Path, config_file: Path) -> str:
    """Builds the `/status` summary text (`FR-TG-16`)."""
    settings = load_settings(config_file)
    v_rows = query_all(db_file, "SELECT status, COUNT(*) AS cnt FROM videos GROUP BY status")
    v_map = {str(r["status"]): int(r["cnt"]) for r in v_rows}

    j_rows = query_all(db_file, "SELECT status, COUNT(*) AS cnt FROM jobs GROUP BY status")
    j_map = {str(r["status"]): int(r["cnt"]) for r in j_rows}

    today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    u_rows = query_all(
        db_file,
        """
        SELECT route, COUNT(*) AS calls, COALESCE(SUM(cost_usd), 0.0) AS cost
        FROM ai_usage
        WHERE day = ?
        GROUP BY route
        """,
        (today_utc,),
    )
    sub_calls = sum(int(r["calls"]) for r in u_rows if r["route"] == "subscription")
    api_calls = sum(int(r["calls"]) for r in u_rows if r["route"] == "api")
    api_cost = sum(float(r["cost"]) for r in u_rows if r["route"] == "api")
    paused = get_setting(db_file, "posting_paused", "0") == "1"

    lines = [
        "📊 TRẠNG THÁI VIDEO CREATOR",
        f"- Chế độ đăng tự động: {'⏸ ĐANG TẠM DỪNG' if paused else '▶️ Đang hoạt động'}",
        f"- Video chờ duyệt: {v_map.get('pending_approval', 0)} | Đã duyệt: {v_map.get('approved', 0)} | Đã xếp lịch: {v_map.get('scheduled', 0)} | Đã đăng: {v_map.get('posted', 0)}",
        f"- Job đang chạy: {j_map.get('running', 0)} | Hàng đợi: {j_map.get('queued', 0)} | Chờ quota: {j_map.get('waiting_quota', 0)}",
        f"- AI hôm nay ({today_utc}): {sub_calls} lượt gói thuê bao ($0) | {api_calls} lượt API (${api_cost:.4f} / trần ${settings.budget.daily_usd:.2f})",
    ]
    return "\n".join(lines)


def execute_command(
    paths: AppPaths,
    *,
    chat_id: int | None,
    user_id: int | None,
    user_name: str,
    command: str,
    args: str = "",
    now_dt: datetime | None = None,
) -> tuple[bool, str, KeyboardRows]:
    """Executes a Telegram slash command with 2-layer allowlist checks (`FR-TG-01`, `FR-TG-16`).

    Read-only commands (`/menu`, `/help`, `/status`, `/schedule`, `/report`) require `allowed_chat_ids`.
    State-mutating commands (`/scan`, `/create`, `/pause`, `/resume`, `/setup`, `/pending`, `/trends`)
    require both `allowed_chat_ids` and `approver_user_ids`.
    """
    settings = load_settings(paths.config_file)
    if chat_id is None or int(chat_id) not in {int(c) for c in settings.telegram.allowed_chat_ids}:
        logger.warning("Ignored command /%s from unauthorized chat_id=%s", command, chat_id)
        return False, "Chat này không nằm trong danh sách được phép.", []

    cmd = command.lstrip("/").split("@")[0].lower().strip()
    clean_args = (args or "").strip().lower()
    actor = f"tg:{user_id}:{(user_name or '').strip() or user_id}"

    # Read-only commands
    if cmd == "menu":
        text, kb = build_menu_message()
        return True, text, kb

    if cmd == "help":
        lines = ["📖 DANH SÁCH LỆNH TELEGRAM:"]
        for c_name, c_desc in BOT_COMMAND_SPECS:
            lines.append(f"• /{c_name} — {c_desc}")
        return True, "\n".join(lines), []

    if cmd == "status":
        return True, build_status_text(paths.db_file, paths.config_file), []

    if cmd == "schedule":
        text, kb = build_schedule_message(paths.db_file, paths.config_file, now_dt=now_dt)
        return True, text, kb

    if cmd == "report":
        from videocreator.reports import daily_summary, weekly_summary

        if clean_args.startswith("week"):
            return True, weekly_summary(paths, now_dt=now_dt), []
        return True, daily_summary(paths, now_dt=now_dt), []

    # Mutating / interactive commands require approver_user_ids check
    allowed, err_msg = check_two_layer_allowlist(chat_id, user_id, settings)
    if not allowed:
        return False, err_msg or "Không có quyền thực hiện lệnh này.", []

    from videocreator.posting.service import set_posting_paused

    if cmd == "pause":
        set_posting_paused(paths.db_file, True, actor=actor)
        return True, "⏸ Đã tạm dừng việc đăng bài tự động. Các bài đã xếp lịch được giữ nguyên.", []

    if cmd == "resume":
        set_posting_paused(paths.db_file, False, actor=actor)
        return True, "▶️ Đã chạy lại việc đăng bài tự động.", []

    if cmd == "scan":
        jid = enqueue_job(paths.db_file, "trend_scan")
        with get_conn(paths.db_file) as conn:
            record_audit(
                conn,
                actor=actor,
                action="trends.scan_requested",
                object_type="job",
                object_id=jid,
            )
        return True, f"🔍 Đã xếp hàng đợi quét xu hướng ngay (Job #{jid}).", []

    if cmd == "create":
        rows = query_all(
            paths.db_file,
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
        kb: KeyboardRows = []
        for r in rows:
            fid = int(r["id"])
            fname = Path(str(r["path"])).name
            scnt = int(r["shot_cnt"] or 0)
            lines.append(f"• #{fid} {fname} ({scnt} shot)")
            kb.append(
                [
                    (f"#{fid}: Tạo 3 bản", f"ftg_ok:{fid}:3"),
                    (f"#{fid}: Tạo 5 bản", f"ftg_ok:{fid}:5"),
                ]
            )
        return True, "\n".join(lines), kb

    if cmd == "trends":
        rows = query_all(
            paths.db_file,
            """
            SELECT * FROM suggestions
            WHERE status IN ('new', 'sent')
            ORDER BY id DESC
            LIMIT 3
            """,
        )
        if not rows:
            return True, "Hiện không có đề xuất xu hướng nào chưa xử lý.", []
        first = rows[0]
        t_item = (
            query_one(
                paths.db_file,
                "SELECT * FROM trend_items WHERE id = ?",
                (first["trend_item_id"],),
            )
            if first.get("trend_item_id")
            else None
        )
        text, kb = build_trend_suggestion_message(first, t_item)
        return True, text, kb

    if cmd == "pending":
        pending = list_pending_approval_videos(paths.db_file)
        if not pending:
            return True, "Hiện không có video nào đang chờ duyệt.", []
        ids_str = ", ".join(f"#{v['id']}" for v in pending)
        return True, f"⏳ Có {len(pending)} video đang chờ duyệt: {ids_str}", []

    if cmd == "setup":
        # Creating forum topics needs the Telegram API; the running bot handles `/setup` itself.
        return False, "Lệnh /setup chỉ chạy được khi gõ trong nhóm Telegram có bot.", []

    return False, f"Lệnh không hỗ trợ: /{cmd}", []


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

    base_utc = (now_dt or datetime.now(timezone.utc)).astimezone(timezone.utc)
    now_iso = base_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    expires_at = str(row["expires_at"])

    with get_conn(paths.db_file) as conn:
        conn.execute(
            "DELETE FROM tg_pending_input WHERE chat_id = ? AND user_id = ?",
            (int(chat_id), int(user_id)),
        )

    if expires_at < now_iso:
        return False, "Phiên nhập thông tin đã hết hạn (quá 10 phút). Vui lòng bấm lại nút trên tin nhắn."

    kind = str(row["kind"])
    ref_id = int(row["ref_id"])
    clean_text = (text or "").strip()
    if not clean_text:
        return False, None

    actor = f"tg:{user_id}:{(user_name or '').strip() or user_id}"

    if kind == "reject_reason":
        safe_reason = clean_text[:300]
        won = reject(paths.db_file, ref_id, by=actor, reason=safe_reason)
        if won:
            return True, f"❌ Đã loại Video #{ref_id} (Lý do: {safe_reason})"
        return True, f"Video #{ref_id} đã được xử lý trước đó."

    if kind.startswith("caption:"):
        plat = kind.split(":", 1)[1].strip().lower()
        max_chars = 2200
        if plat in settings.platform_limits:
            max_chars = int(settings.platform_limits[plat].max_caption_chars)
        truncated = clean_text[:max_chars]

        v_row = query_one(paths.db_file, "SELECT captions_json FROM videos WHERE id = ?", (ref_id,))
        if v_row is None:
            return True, f"Không tìm thấy Video #{ref_id}."
        try:
            caps = json.loads(str(v_row.get("captions_json") or "{}"))
        except Exception:
            caps = {}
        if not isinstance(caps.get(plat), dict):
            caps[plat] = {"text": truncated, "hashtags": []}
        else:
            caps[plat]["text"] = truncated

        with get_conn(paths.db_file) as conn:
            conn.execute(
                "UPDATE videos SET captions_json = ? WHERE id = ?",
                (json.dumps(caps, ensure_ascii=False), ref_id),
            )
            record_audit(
                conn,
                actor=actor,
                action="video.caption_updated",
                object_type="video",
                object_id=ref_id,
                detail=f"platform={plat}, len={len(truncated)}",
            )
        return True, f"✏️ Đã cập nhật caption {plat.upper()} cho Video #{ref_id} ({len(truncated)} ký tự)."

    return False, None


# --- Instruction Presets (`FR-PLN-07`) ---


def create_preset(db_file: Path, *, name: str, kind: str, body: str) -> int:
    with get_conn(db_file) as conn:
        cur = conn.execute(
            """
            INSERT INTO presets (name, kind, body)
            VALUES (?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                kind = excluded.kind,
                body = excluded.body
            """,
            (name.strip(), kind.strip(), body.strip()),
        )
        row = conn.execute("SELECT id FROM presets WHERE name = ?", (name.strip(),)).fetchone()
        return int(row["id"]) if row else int(cur.lastrowid or 0)


def list_presets(db_file: Path) -> list[dict[str, Any]]:
    return query_all(db_file, "SELECT * FROM presets ORDER BY id ASC")


def export_presets_json(db_file: Path) -> str:
    rows = list_presets(db_file)
    export_items = [
        {"name": r["name"], "kind": r["kind"], "body": r["body"]}
        for r in rows
    ]
    return json.dumps({"presets": export_items}, ensure_ascii=False, indent=2)


def import_presets_json(db_file: Path, raw_json: str) -> int:
    data = json.loads(raw_json)
    items = data.get("presets") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise ValueError("Invalid presets JSON format")
    count = 0
    for item in items:
        if isinstance(item, dict) and item.get("name") and item.get("body"):
            create_preset(
                db_file,
                name=str(item["name"]),
                kind=str(item.get("kind") or "writer"),
                body=str(item["body"]),
            )
            count += 1
    return count

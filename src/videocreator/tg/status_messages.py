"""Texts of the `/menu`, `/schedule` and `/status` commands."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from videocreator.config import load_settings
from videocreator.db import get_setting, query_all
from videocreator.tg.messages import KeyboardRows
from videocreator.timeutil import UTC_ISO_FORMAT, utc_now


def build_schedule_message(
    db_file: Path,
    config_file: Path,
    now_dt: datetime | None = None,
) -> tuple[str, KeyboardRows]:
    """Builds `/schedule` text + action buttons for today and tomorrow's scheduled posts."""
    settings = load_settings(config_file)
    tz = ZoneInfo(settings.schedule.timezone)
    base_utc = utc_now(now_dt)
    end_utc = base_utc + timedelta(days=2)

    rows = query_all(
        db_file,
        """
        SELECT p.id, p.video_id, p.scheduled_at, p.status, a.platform, a.name AS account_name
        FROM posts p
        JOIN accounts a ON p.account_id = a.id
        WHERE p.status = 'scheduled' AND p.scheduled_at <= ?
        ORDER BY p.scheduled_at ASC, p.id ASC
        LIMIT 12
        """,
        (end_utc.strftime(UTC_ISO_FORMAT),),
    )
    if not rows:
        return "📅 Hiện không có bài đăng nào trong lịch hôm nay & ngày mai.", []

    lines = [f"📅 Lịch đăng ({settings.schedule.timezone}):"]
    keyboard: KeyboardRows = []
    for r in rows:
        pid = int(r["id"])
        vid = int(r["video_id"])
        iso_str = str(r["scheduled_at"]).replace("Z", "+00:00")
        try:
            local_str = datetime.fromisoformat(iso_str).astimezone(tz).strftime("%d/%m %H:%M")
        except Exception:
            local_str = str(r["scheduled_at"])
        lines.append(f"• Post #{pid}: Video #{vid} -> {r['platform']} ({r['account_name']}) lúc {local_str}")
        keyboard.append(
            [
                (f"🚀 Đăng ngay #{pid}", f"pst_now:{pid}"),
                (f"🗑 Huỷ #{pid}", f"pst_del:{pid}"),
            ]
        )
    return "\n".join(lines), keyboard


def build_menu_message() -> tuple[str, KeyboardRows]:
    text = (
        "🎛 BẢNG ĐIỀU KHIỂN TELEGRAM — VIDEO CREATOR\n"
        "• /status — Trạng thái hệ thống & ngân sách AI\n"
        "• /pending — Gửi lại các video đang chờ duyệt\n"
        "• /schedule — Xem lịch đăng hôm nay & ngày mai\n"
        "• /trends — Gửi lại các đề xuất xu hướng chưa xử lý\n"
        "• /scan — Quét xu hướng ngay\n"
        "• /create — Chọn footage mới nhất để tạo video\n"
        "• /pause | /resume — Tạm dừng / Chạy lại đăng tự động\n"
        "• /report | /report week — Báo cáo ngày / Báo cáo tuần"
    )
    keyboard: KeyboardRows = [
        [("📊 Trạng thái", "cmd:status"), ("⏳ Chờ duyệt", "cmd:pending")],
        [("📅 Lịch đăng", "cmd:schedule"), ("🔥 Đề xuất", "cmd:trends")],
        [("🔍 Quét ngay", "cmd:scan"), ("📈 Báo cáo ngày", "cmd:report")],
    ]
    return text, keyboard


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


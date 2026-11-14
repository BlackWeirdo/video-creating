"""Pure message and inline-keyboard builders for the Telegram Control Center (Phase 16)."""
from __future__ import annotations

import json
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from videocreator.config import Settings, load_settings
from videocreator.db import query_all

ButtonSpec = tuple[str, str]  # (label, callback_data <= 64 bytes)
KeyboardRows = list[list[ButtonSpec]]


def is_quiet_hours(settings: Settings, now_dt: datetime | None = None) -> bool:
    """Returns True if `now_dt` falls inside `settings.telegram.quiet_hours` (default `22:00-07:00` in `schedule.timezone`)."""
    raw = (settings.telegram.quiet_hours or "").strip()
    if "-" not in raw:
        return False
    start_s, end_s = raw.split("-", 1)
    try:
        sh, sm = [int(x) for x in start_s.strip().split(":")]
        eh, em = [int(x) for x in end_s.strip().split(":")]
        t_start = time(sh, sm)
        t_end = time(eh, em)
    except Exception:
        return False

    tz = ZoneInfo(settings.schedule.timezone)
    local_t = (now_dt or datetime.now(timezone.utc)).astimezone(tz).time()
    if t_start <= t_end:
        return t_start <= local_t < t_end
    return local_t >= t_start or local_t < t_end


def build_trend_suggestion_message(
    suggestion: dict[str, Any],
    trend_item: dict[str, Any] | None = None,
) -> tuple[str, KeyboardRows]:
    """Builds the Round 1 trend suggestion message + keyboard (`FR-TG-10`).

    If `missing_shots` is non-empty, includes 'cần quay thêm: ...' and omits the create buttons.
    """
    sid = int(suggestion["id"])
    text = str(str(suggestion.get("text") or ""))
    try:
        formula = json.loads(str(suggestion.get("formula_json") or "{}"))
    except Exception:
        formula = {}

    formula_name = str(str(formula.get("formula") or "hook-first"))
    missing = str(formula.get("missing_shots") or "").strip()
    if not missing and "cần quay thêm:" in str(suggestion.get("text") or "").lower():
        missing = str(suggestion.get("text"))

    lines = [f"🔥 Đề xuất xu hướng #{sid}"]
    if trend_item:
        author = str(str(trend_item.get("author") or "Brand"))
        src = str(str(trend_item.get("source") or "trend"))
        url = str(trend_item.get("url") or "")
        lines.append(f"• Nguồn: {src} — {author}")
        if url:
            lines.append(f"• Link: {url}")
        try:
            m = json.loads(str(trend_item.get("metrics_json") or "{}"))
            if m.get("days_running"):
                lines.append(f"• Quảng cáo chạy: {m['days_running']} ngày (EU reach: {m.get('eu_reach', 0)})")
            elif m:
                lines.append(f"• Số liệu: 👁 {m.get('views', 0)} | ❤️ {m.get('likes', 0)} | 💬 {m.get('comments', 0)}")
        except Exception:
            pass
        try:
            an = json.loads(str(trend_item.get("analysis_json") or "{}"))
            if an.get("why_it_works"):
                lines.append(f"• Vì sao hiệu quả: {str(str(an['why_it_works']))}")
        except Exception:
            pass

    lines.append(f"• Công thức: {formula_name}")
    lines.append(f"• Ý tưởng: {text}")

    if missing:
        if "cần quay thêm" not in text.lower():
            lines.append(f"⚠️ Cần quay thêm: {str(missing)}")
        return "\n".join(lines), [[("Bỏ qua", f"sg_no:{sid}")]]

    keyboard: KeyboardRows = [
        [
            ("🎬 Tạo 1 video", f"sg_ok:{sid}:1"),
            ("🎬 Tạo 3 bản", f"sg_ok:{sid}:3"),
            ("Bỏ qua", f"sg_no:{sid}"),
        ]
    ]
    return "\n".join(lines), keyboard


def build_new_footage_message(
    footage_id: int,
    filename: str,
    shot_count: int,
) -> tuple[str, KeyboardRows]:
    """Builds the Round 1 new footage notification message + keyboard (`FR-TG-11`)."""
    safe_name = str(filename)
    text = f"📹 Footage {safe_name} (#{footage_id}): {shot_count} shot. Tạo mấy video?"
    keyboard: KeyboardRows = [
        [
            ("3 bản", f"ftg_ok:{footage_id}:3"),
            ("5 bản", f"ftg_ok:{footage_id}:5"),
            ("Bỏ qua", f"ftg_no:{footage_id}"),
        ]
    ]
    return text, keyboard


def build_approval_message(
    video_item: dict[str, Any],
    *,
    account_names: list[str] | None = None,
    next_slot_str: str | None = None,
) -> tuple[str, KeyboardRows]:
    """Builds the Round 2 video approval caption + 6-button keyboard (`FR-TG-13`)."""
    vid = int(video_item["id"])
    title = str(str(video_item.get("title") or f"Video #{vid}"))
    formula = str(str(video_item.get("formula") or "hook-first"))
    dur = float(video_item.get("duration_s") or 0.0)
    prods = ", ".join(video_item.get("product_names") or []) or "Không gắn sản phẩm"

    lines = [
        f"🎬 Video #{vid}: {title}",
        f"📐 Công thức: {formula} | Thời lượng: {dur:.1f}s",
        f"💍 Sản phẩm: {prods}",
    ]
    if video_item.get("quality_score") is not None:
        score_val = float(video_item["quality_score"])
        notes_val = str(video_item.get("quality_notes") or "").strip()
        lines.append(f"⭐ Điểm tự động: {score_val:.1f}/10" + (f" ({notes_val[:80]})" if notes_val else ""))
    elif video_item.get("quality_notes"):
        notes_val = str(video_item.get("quality_notes") or "").strip()
        if notes_val:
            lines.append(f"ℹ️ Ghi chú: {notes_val[:120]}")

    if account_names:
        lines.append(f"📡 Tài khoản đích: {', '.join(account_names)}")
    if next_slot_str:
        lines.append(f"🕒 Khung giờ dự kiến: {next_slot_str}")

    if video_item.get("has_ai_broll"):
        lines.append("🤖 Nhãn: [Có cảnh phụ AI B-roll]")
    if video_item.get("has_studio_effects") or str(video_item.get("engine") or "") == "studio":
        lines.append("✨ Có hiệu ứng chuyển động trên footage (Studio)")

    unverified = video_item.get("unverified_claims") or []
    if unverified:
        lines.append("⚠️ CẢNH BÁO ĐỐI CHIẾU SẢN PHẨM (chưa có trong facts_json):")
        for c in unverified[:3]:
            lines.append(f"  • {c}")

    preflight = video_item.get("preflight") or {}
    pf_errs: list[str] = []
    for _plat, errs in preflight.items():
        if errs:
            pf_errs.extend(errs)
    if pf_errs:
        lines.append("⚠️ Cảnh báo định dạng nền tảng:")
        for pe in pf_errs[:3]:
            lines.append(f"  • {pe}")

    caps = video_item.get("captions") or {}
    fb_cap = (caps.get("facebook") or {}).get("text") or ""
    if fb_cap:
        lines.append(f"\n📝 Caption (FB): {fb_cap[:220]}")

    return "\n".join(lines)[:1000], build_approval_keyboard(vid)


def build_approval_keyboard(video_id: int) -> KeyboardRows:
    """The 6 main buttons of a pending video; sub-menus return here through their back button."""
    vid = int(video_id)
    return [
        [
            ("✅ Duyệt, xếp lịch", f"ok:{vid}"),
            ("🚀 Đăng ngay", f"now_ask:{vid}"),
        ],
        [
            ("❌ Loại", f"no_ask:{vid}"),
            ("🔄 Làm lại", f"redo:{vid}"),
        ],
        [
            ("📡 Tài khoản", f"acc_menu:{vid}"),
            ("✏️ Caption", f"cap_menu:{vid}"),
        ],
    ]


def build_account_toggle_keyboard(
    video_id: int,
    accounts: list[dict[str, Any]],
    selected_ids: set[int],
) -> KeyboardRows:
    """Builds per-account toggle keyboard (`acc_tog:<vid>:<acc_id>`) + `Xong` (`acc_done:<vid>`)."""
    rows: KeyboardRows = []
    for a in accounts:
        aid = int(a["id"])
        checked = "✅" if aid in selected_ids else "⬜"
        label = f"{checked} [{a['platform']}] {a['name']}"[:40]
        rows.append([(label, f"acc_tog:{video_id}:{aid}")])
    rows.append([("✔️ Xong", f"acc_done:{video_id}")])
    return rows


def build_post_now_confirm_keyboard(video_id: int) -> KeyboardRows:
    """1-step confirmation before immediate publishing (`now_yes:<vid>`)."""
    return [
        [
            ("⚠️ Chắc chắn đăng ngay?", f"now_yes:{video_id}"),
            ("Huỷ", f"now_cancel:{video_id}"),
        ]
    ]


def build_schedule_message(
    db_file: Path,
    config_file: Path,
    now_dt: datetime | None = None,
) -> tuple[str, KeyboardRows]:
    """Builds `/schedule` text + action buttons for today and tomorrow's scheduled posts."""
    settings = load_settings(config_file)
    tz = ZoneInfo(settings.schedule.timezone)
    base_utc = (now_dt or datetime.now(timezone.utc)).astimezone(timezone.utc)
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
        (end_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),),
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

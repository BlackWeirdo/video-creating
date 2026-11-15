"""Pure message and inline-keyboard builders for the Telegram Control Center (Phase 16)."""
from __future__ import annotations
import json
from typing import Any

from videocreator.jsonutil import loads_or


ButtonSpec = tuple[str, str]  # (label, callback_data <= 64 bytes)
KeyboardRows = list[list[ButtonSpec]]


def build_trend_suggestion_message(
    suggestion: dict[str, Any],
    trend_item: dict[str, Any] | None = None,
) -> tuple[str, KeyboardRows]:
    """Builds the Round 1 trend suggestion message + keyboard (`FR-TG-10`).

    If `missing_shots` is non-empty, includes 'cần quay thêm: ...' and omits the create buttons.
    """
    sid = int(suggestion["id"])
    text = str(str(suggestion.get("text") or ""))
    formula = loads_or(suggestion.get("formula_json"), {})

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

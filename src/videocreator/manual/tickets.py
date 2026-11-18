"""Manual work tickets (`manual_tickets`) for creating B-roll in subscription apps (Phase 14 & 18)."""
from __future__ import annotations
import logging
import re
from datetime import datetime, timedelta

from videocreator.db import get_conn, get_write_conn, query_all, query_one, record_audit
from videocreator.manual.fulfill import ALLOWED_VIDEO_EXTS, fulfill_manual_ticket
from videocreator.paths import AppPaths
from videocreator.tg.sender import send_text
from videocreator.timeutil import UTC_ISO_FORMAT, utc_now

logger = logging.getLogger("videocreator.manual.tickets")

TICKET_FILENAME_RE = re.compile(r"ticket[_-]?(\d+)", re.IGNORECASE)


def create_manual_ticket(
    paths: AppPaths,
    *,
    prompt: str,
    kind: str = "broll",
    seconds: int = 6,
    ref_path: str | None = None,
    actor: str = "ui",
) -> int:
    """Creates an open manual ticket (`FR-BRL-02`) and notifies Telegram."""
    clean_prompt = prompt.strip()
    if not clean_prompt:
        raise ValueError("Prompt is required for manual ticket")

    full_prompt = f"[9:16 dọc, {seconds}s, cảnh phụ không có sản phẩm thật] {clean_prompt}"
    with get_write_conn(paths.db_file) as conn:
        cur = conn.execute(
            """
            INSERT INTO manual_tickets (kind, prompt, ref_path, status)
            VALUES (?, ?, ?, 'open')
            """,
            (kind, full_prompt, ref_path),
        )
        ticket_id = int(cur.lastrowid or 0)
        record_audit(
            conn,
            actor=actor,
            action="manual_ticket.created",
            object_type="manual_ticket",
            object_id=ticket_id,
            detail=full_prompt[:140],
        )

    msg_text = (
        f"🛠 Phiếu việc tay #{ticket_id} (Cảnh phụ B-roll — $0 gói thuê bao)\n"
        f"• Thông số: 9:16 dọc, {seconds} giây\n"
        f"• Prompt sao chép vào Muse / Gemini / Flow:\n{full_prompt}\n\n"
        f"📥 Sau khi tải clip về, tải lên tại trang /manual hoặc thả vào thư mục inbox/ với tên `ticket_{ticket_id}.mp4`."
    )
    try:
        sent_ids = send_text(paths, msg_text, topic="manual")
        if sent_ids:
            with get_conn(paths.db_file) as conn:
                conn.execute(
                    "UPDATE manual_tickets SET tg_message_id = ? WHERE id = ?",
                    (sent_ids[0], ticket_id),
                )
    except Exception as exc:
        logger.debug("Manual ticket Telegram send skipped: %s", exc)

    return ticket_id


def scan_inbox_for_tickets(paths: AppPaths) -> list[int]:
    """Scans `data_dir/inbox/` for `ticket_<id>.mp4` files and fulfills matching open tickets."""
    inbox_dir = paths.data_dir / "inbox"
    if not inbox_dir.exists():
        return []
    fulfilled: list[int] = []
    for f in sorted(inbox_dir.iterdir()):
        if not f.is_file() or f.suffix.lower() not in ALLOWED_VIDEO_EXTS:
            continue
        m = TICKET_FILENAME_RE.search(f.stem)
        if not m:
            continue
        tid = int(m.group(1))
        row = query_one(
            paths.db_file,
            "SELECT id FROM manual_tickets WHERE id = ? AND status IN ('open', 'reminded')",
            (tid,),
        )
        if row is None:
            continue
        try:
            fulfill_manual_ticket(paths, tid, f, actor="inbox_watcher")
            f.unlink(missing_ok=True)
            fulfilled.append(tid)
        except Exception as exc:
            logger.warning("Failed to fulfill ticket #%d from inbox file %s: %s", tid, f.name, exc)
    return fulfilled


def expire_stale_tickets(
    paths: AppPaths,
    *,
    now_dt: datetime | None = None,
    max_age_hours: float = 48.0,
    remind_grace_hours: float = 1.0,
) -> list[int]:
    """Reminds open tickets older than 48h once (`open -> reminded`), then cancels reminded tickets after grace (`FR-BRL-02`)."""
    base_utc = utc_now(now_dt)
    now_iso = base_utc.strftime(UTC_ISO_FORMAT)
    cutoff_iso = (base_utc - timedelta(hours=max_age_hours)).strftime(UTC_ISO_FORMAT)
    remind_cutoff_iso = (base_utc - timedelta(hours=remind_grace_hours)).strftime(UTC_ISO_FORMAT)

    cancelled: list[int] = []
    reminded_rows: list[dict[str, object]] = []
    with get_write_conn(paths.db_file) as conn:
        to_cancel = conn.execute(
            """
            SELECT id FROM manual_tickets
            WHERE status = 'reminded'
              AND created_at <= ?
              AND COALESCE(reminded_at, created_at) <= ?
            """,
            (cutoff_iso, remind_cutoff_iso),
        ).fetchall()
        to_remind = conn.execute(
            """
            SELECT id, prompt FROM manual_tickets
            WHERE status = 'open' AND created_at <= ?
            """,
            (cutoff_iso,),
        ).fetchall()

        for r in to_cancel:
            tid = int(r["id"])
            cur = conn.execute(
                """
                UPDATE manual_tickets
                SET status = 'cancelled',
                    closed_at = ?
                WHERE id = ? AND status = 'reminded'
                """,
                (now_iso, tid),
            )
            if cur.rowcount:
                cancelled.append(tid)

        for r in to_remind:
            tid = int(r["id"])
            cur = conn.execute(
                """
                UPDATE manual_tickets
                SET status = 'reminded',
                    reminded_at = ?
                WHERE id = ? AND status = 'open'
                """,
                (now_iso, tid),
            )
            if cur.rowcount:
                reminded_rows.append(dict(r))

    for r in reminded_rows:
        tid = int(r["id"])
        try:
            send_text(
                paths,
                f"⏰ Nhắc phiếu việc tay #{tid} đã quá 48 giờ chưa nạp file MP4.\n"
                f"Prompt: {str(r.get('prompt') or '')[:160]}\n"
                f"Vui lòng trả lời tin phiếu bằng file MP4 hoặc thả `ticket_{tid}.mp4` vào `inbox/` trước khi phiếu tự huỷ.",
                topic="manual",
            )
        except Exception as exc:
            logger.debug("Manual ticket reminder Telegram send skipped: %s", exc)

    return cancelled

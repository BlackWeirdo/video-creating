"""Receives a video sent to the bot as the result of a manual work ticket."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from videocreator.config import load_settings
from videocreator.db import query_one
from videocreator.paths import AppPaths
from videocreator.tg.access import check_two_layer_allowlist

TICKET_NUMBER_IN_TEXT_RE = re.compile(r"#(\d+)")


def _ticket_id_from_reply(db_file: Path, replied_message: Any) -> int | None:
    """Ticket of the message the video replies to: by stored message id, else by `#<id>` in its text."""
    ticket_row = query_one(
        db_file,
        "SELECT id FROM manual_tickets WHERE tg_message_id = ? AND status IN ('open', 'reminded')",
        (int(replied_message.message_id),),
    )
    if ticket_row:
        return int(ticket_row["id"])
    replied_text = str(replied_message.text or replied_message.caption or "")
    match = TICKET_NUMBER_IN_TEXT_RE.search(replied_text)
    return int(match.group(1)) if match else None


def find_ticket_id(db_file: Path, message: Any, media_obj: Any) -> int | None:
    """Ticket a received video belongs to: the replied-to ticket message, else `ticket_<id>` in the file name."""
    from videocreator.manual.tickets import TICKET_FILENAME_RE

    if message.reply_to_message:
        ticket_id = _ticket_id_from_reply(db_file, message.reply_to_message)
        if ticket_id is not None:
            return ticket_id
    file_name = str(getattr(media_obj, "file_name", "") or message.caption or "")
    match = TICKET_FILENAME_RE.search(file_name)
    return int(match.group(1)) if match else None


async def receive_ticket_video(
    paths: AppPaths, message: Any, *, chat_id: int | None, user_id: int | None, user_name: str
) -> None:
    """Downloads a video sent by an approver and files it under its manual ticket as a B-roll shot."""
    from videocreator.manual.fulfill import fulfill_manual_ticket

    allowed, _err = check_two_layer_allowlist(chat_id, user_id, load_settings(paths.config_file))
    if not allowed:
        return
    media_obj = message.video or message.document
    if media_obj is None:
        return
    ticket_id = find_ticket_id(paths.db_file, message, media_obj)
    if ticket_id is None:
        return

    tmp_file = paths.work_dir / f"tg_ticket_{ticket_id}.mp4"
    tmp_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        tg_file = await media_obj.get_file()
        await tg_file.download_to_drive(custom_path=str(tmp_file))
        _asset_id, shot_id = fulfill_manual_ticket(
            paths,
            ticket_id,
            tmp_file,
            actor=f"tg:{user_id}:{user_name}",
        )
        await message.reply_text(
            f"✅ Đã nhận video phiếu việc tay #{ticket_id} và đưa vào kho cảnh phụ (Shot #{shot_id})."
        )
    except Exception as exc:
        await message.reply_text(f"❌ Không nạp được video cho phiếu #{ticket_id}: {exc}")
    finally:
        tmp_file.unlink(missing_ok=True)

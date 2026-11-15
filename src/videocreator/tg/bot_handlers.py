"""Update handlers of the running Telegram bot: slash commands, menu buttons, callbacks and replies."""
from __future__ import annotations

import asyncio
from typing import Any

from videocreator.approval_queue import list_pending_approval_videos
from videocreator.config import load_settings
from videocreator.paths import AppPaths
from videocreator.tg.access import check_two_layer_allowlist
from videocreator.tg.approval_notify import notify_pending_async
from videocreator.tg.callbacks import route_callback
from videocreator.tg.commands import execute_command
from videocreator.tg.link_command import handle_link_command
from videocreator.tg.notify import send_open_suggestions_async
from videocreator.tg.pending_input import handle_pending_reply_input
from videocreator.tg.sender import to_inline_markup
from videocreator.tg.ticket_upload import receive_ticket_video
from videocreator.tg.topics import setup_topics

# Commands answered by the bot itself (they send messages or call the Telegram API); approvers only.
APPROVER_BOT_COMMANDS = ("pending", "trends", "setup")


def sender_identity(chat: Any, user: Any) -> tuple[int | None, int | None, str]:
    """`(chat_id, user_id, user_name)` of the chat and user behind an update."""
    chat_id = chat.id if chat else None
    user_id = user.id if user else None
    user_name = (user.full_name or user.username or str(user_id)) if user else "user"
    return chat_id, user_id, user_name


async def _react(message: Any, emoji: str) -> None:
    try:
        await message.set_reaction(emoji)
    except Exception:
        pass


async def _show_callback_result(query: Any, reply_msg: str, state_changed: bool, new_keyboard: Any) -> None:
    """Swaps the keyboard, or appends the outcome to the message once the action is final."""
    if new_keyboard is not None:
        await query.edit_message_reply_markup(reply_markup=to_inline_markup(new_keyboard))
        return
    if not state_changed:
        return
    if query.message.caption is not None:
        new_caption = f"{query.message.caption or ''}\n\n{reply_msg}"[:1020]
        await query.edit_message_caption(caption=new_caption, reply_markup=None)
        return
    if query.message.text is not None:
        new_text = f"{query.message.text or ''}\n\n{reply_msg}"[:4000]
        await query.edit_message_text(text=new_text, reply_markup=None)


class BotUpdateHandlers:
    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths

    async def on_command(self, update: Any, context: Any) -> None:
        message = update.message
        if not message or not message.text:
            return
        chat_id, user_id, user_name = sender_identity(update.effective_chat, update.effective_user)
        parts = message.text.strip().split(maxsplit=1)
        cmd_name = parts[0].lstrip("/").split("@")[0].lower()
        cmd_args = parts[1] if len(parts) > 1 else ""

        await _react(message, "👀")
        ok = await self.run_command(message, context.bot, chat_id, user_id, user_name, cmd_name, cmd_args)
        await _react(message, "👌" if ok else "👎")

    async def run_command(
        self,
        message: Any,
        bot: Any,
        chat_id: int | None,
        user_id: int | None,
        user_name: str,
        cmd_name: str,
        cmd_args: str = "",
    ) -> bool:
        """Runs one command and answers with a new message. Shared by slash commands and menu buttons."""
        if cmd_name in APPROVER_BOT_COMMANDS:
            allowed, err_msg = check_two_layer_allowlist(chat_id, user_id, load_settings(self.paths.config_file))
            if not allowed:
                await message.reply_text(err_msg or "Không có quyền.")
                return False
        if cmd_name == "pending":
            pending = list_pending_approval_videos(self.paths.db_file)
            if not pending:
                await message.reply_text("Hiện không có video nào đang chờ duyệt.")
            for video in pending:
                await notify_pending_async(self.paths, int(video["id"]))
            return True
        if cmd_name == "trends":
            sent = await send_open_suggestions_async(
                self.paths, statuses=("new", "sent"), respect_quiet_hours=False
            )
            if not sent:
                await message.reply_text("Hiện không có đề xuất xu hướng nào chưa xử lý.")
            return True
        if cmd_name == "setup":
            await message.reply_text(await setup_topics(self.paths, bot, message.chat))
            return True
        if cmd_name == "link":
            # yt-dlp can take several seconds: keep it off the bot's event loop.
            ok, reply_text = await asyncio.to_thread(
                handle_link_command,
                self.paths,
                chat_id=chat_id,
                user_id=user_id,
                user_name=user_name,
                args=cmd_args,
            )
            await message.reply_text(reply_text[:4096])
            return ok

        ok, reply_text, keyboard = execute_command(
            self.paths,
            chat_id=chat_id,
            user_id=user_id,
            user_name=user_name,
            command=cmd_name,
            args=cmd_args,
        )
        await message.reply_text(reply_text[:4096], reply_markup=to_inline_markup(keyboard))
        return ok

    async def on_callback(self, update: Any, context: Any) -> None:
        query = update.callback_query
        if query is None:
            return
        chat_id, user_id, user_name = sender_identity(update.effective_chat, query.from_user)
        data = query.data or ""
        if data.startswith("cmd:") and query.message:
            # Menu buttons: the answer is a full message, not a 190-character popup.
            await query.answer()
            await self.run_command(query.message, context.bot, chat_id, user_id, user_name, data.split(":", 1)[1])
            return
        allowed, reply_msg, state_changed, new_keyboard = route_callback(
            self.paths,
            chat_id=chat_id,
            user_id=user_id,
            user_name=user_name,
            data=data,
        )
        await query.answer(reply_msg[:190], show_alert=not allowed)
        if not allowed or not query.message:
            return
        try:
            await _show_callback_result(query, reply_msg, state_changed, new_keyboard)
        except Exception:
            pass

    async def on_text_reply(self, update: Any, context: Any) -> None:
        message = update.message
        if not message or not message.text:
            return
        chat_id, user_id, user_name = sender_identity(update.effective_chat, update.effective_user)
        handled, response_text = handle_pending_reply_input(
            self.paths,
            chat_id=chat_id,
            user_id=user_id,
            user_name=user_name,
            text=message.text,
        )
        if handled and response_text:
            await message.reply_text(response_text)

    async def on_video_reply(self, update: Any, context: Any) -> None:
        if not update.message:
            return
        chat_id, user_id, user_name = sender_identity(update.effective_chat, update.effective_user)
        await receive_ticket_video(
            self.paths, update.message, chat_id=chat_id, user_id=user_id, user_name=user_name
        )

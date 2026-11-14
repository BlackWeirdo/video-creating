"""Telegram approval & control center bot, 2-layer allowlist, 720p preview fallback, and notification hooks (Phase 06 & Phase 16)."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from videocreator.api.routes_products import list_products
from videocreator.approvals import enrich_approval_video, list_pending_approval_videos
from videocreator.config import Settings, load_settings
from videocreator.db import get_conn, get_setting, query_all, query_one, set_setting
from videocreator.paths import AppPaths, get_paths
from videocreator.pipeline.ffmpeg import run_ffmpeg
from videocreator.secrets_store import SecretsStore
from videocreator.tg.callbacks import check_two_layer_allowlist, route_callback
from videocreator.posting.slots import default_target_account_ids
from videocreator.tg.handlers import (
    BOT_COMMAND_SPECS,
    TOPIC_NAMES,
    build_status_text,
    execute_command,
    handle_pending_reply_input,
)
from videocreator.tg.messages import (
    KeyboardRows,
    build_approval_message,
    build_new_footage_message,
    build_trend_suggestion_message,
    is_quiet_hours,
)

logger = logging.getLogger("videocreator.telegram")

CALLBACK_RE = re.compile(r"^(ok|no):(\d+)$")
MAX_TELEGRAM_VIDEO_MB = 45.0


def is_chat_allowed(chat_id: int | None, settings: Settings) -> bool:
    if chat_id is None:
        return False
    return int(chat_id) in {int(c) for c in settings.telegram.allowed_chat_ids}


def is_user_approver(user_id: int | None, settings: Settings) -> bool:
    if user_id is None:
        return False
    if not settings.telegram.approver_user_ids:
        return True
    return int(user_id) in {int(u) for u in settings.telegram.approver_user_ids}


def format_approval_caption(video_item: dict[str, Any]) -> str:
    caption, _kb = build_approval_message(video_item)
    return caption


def _to_inline_markup(rows: KeyboardRows | None) -> Any:
    if not rows:
        return None
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(label, callback_data=cb_data) for label, cb_data in row]
            for row in rows
        ]
    )


def ensure_telegram_preview_video(
    paths: AppPaths,
    master_path: Path,
    video_id: int,
    *,
    max_mb: float = MAX_TELEGRAM_VIDEO_MB,
) -> Path:
    """Returns `master_path` if under `max_mb`, otherwise transcodes a 720p preview copy (`FR-APR-04`, `FR-TG-13`)."""
    size_mb = master_path.stat().st_size / (1024 * 1024)
    if size_mb <= max_mb:
        return master_path

    preview_path = paths.work_dir / f"tg_preview_720p_{video_id}.mp4"
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(
        [
            "-i",
            str(master_path.resolve()),
            "-vf",
            "scale=720:1280:force_original_aspect_ratio=decrease,pad=720:1280:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "26",
            "-c:a",
            "aac",
            "-b:a",
            "96k",
            str(preview_path.resolve()),
        ]
    )
    return preview_path


def process_approval_callback(
    db_file: Path,
    config_file: Path,
    *,
    chat_id: int | None,
    user_id: int | None,
    user_name: str,
    data: str,
    now_dt: datetime | None = None,
) -> tuple[bool, str, bool]:
    """Processes any Telegram callback query via the single-point router (`FR-TG-01`).

    Returns `(allowed, response_message, won_transition)`.
    """
    paths = get_paths(db_file.parent)
    allowed, msg, won, _kb = route_callback(
        paths,
        chat_id=chat_id,
        user_id=user_id,
        user_name=user_name,
        data=data,
        now_dt=now_dt,
    )
    return allowed, msg, won


TOPICS_SETTING_KEY = "tg_topics_json"


def topic_thread_id(paths: AppPaths, chat_id: int, topic: str | None) -> int | None:
    """Forum topic of `chat_id` created by `/setup` for `topic` (`FR-TG-02`); None sends to the general chat."""
    if not topic:
        return None
    try:
        saved = json.loads(get_setting(paths.db_file, TOPICS_SETTING_KEY) or "{}")
        if int(saved.get("chat_id") or 0) != int(chat_id):
            return None
        thread = (saved.get("threads") or {}).get(topic)
        return int(thread) if thread else None
    except (ValueError, TypeError, AttributeError):
        return None


async def send_text_async(
    paths: AppPaths,
    text: str,
    *,
    keyboard: KeyboardRows | None = None,
    respect_quiet_hours: bool = False,
    topic: str | None = None,
) -> list[int]:
    """Sends `text` (and optional inline keyboard) to all `allowed_chat_ids`, into `topic` where set up."""
    secrets = SecretsStore(paths.secrets_file)
    token = secrets.get("TELEGRAM_BOT_TOKEN")
    settings = load_settings(paths.config_file)
    if not token or not settings.telegram.allowed_chat_ids:
        return []
    if respect_quiet_hours and is_quiet_hours(settings):
        logger.info("Suppressed non-urgent Telegram message during quiet hours")
        return []

    from telegram import Bot

    markup = _to_inline_markup(keyboard)
    msg_ids: list[int] = []
    async with Bot(token=token) as bot:
        for chat_id in settings.telegram.allowed_chat_ids:
            try:
                msg = await bot.send_message(
                    chat_id=chat_id,
                    text=text[:4096],
                    reply_markup=markup,
                    message_thread_id=topic_thread_id(paths, int(chat_id), topic),
                )
                msg_ids.append(int(msg.message_id))
            except Exception as exc:
                logger.warning("Failed to send Telegram message to chat %s: %s", chat_id, exc)
    return msg_ids


def send_text(
    paths: AppPaths,
    text: str,
    *,
    keyboard: KeyboardRows | None = None,
    respect_quiet_hours: bool = False,
    topic: str | None = None,
) -> list[int]:
    """Synchronous helper to send a Telegram alert/report message."""
    coro = send_text_async(
        paths, text, keyboard=keyboard, respect_quiet_hours=respect_quiet_hours, topic=topic
    )
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    loop.create_task(coro)
    return []


def notify_new_footage(
    paths: AppPaths,
    footage_id: int,
    filename: str,
    shot_count: int,
) -> list[int]:
    """Sends Round 1 new footage notification with `3 bản` / `5 bản` / `Bỏ qua` buttons (`FR-FTG-09`, `FR-TG-11`)."""
    text, kb = build_new_footage_message(footage_id, filename, shot_count)
    return send_text(paths, text, keyboard=kb, respect_quiet_hours=True, topic="approvals")


def notify_trend_suggestion(
    paths: AppPaths,
    suggestion: dict[str, Any],
    trend_item: dict[str, Any] | None = None,
) -> list[int]:
    """Sends Round 1 trend suggestion notification with `Tạo 1 video` / `Tạo 3 bản` / `Bỏ qua` (`FR-TG-10`)."""
    text, kb = build_trend_suggestion_message(suggestion, trend_item)
    return send_text(paths, text, keyboard=kb, respect_quiet_hours=True, topic="trends")


async def send_open_suggestions_async(
    paths: AppPaths,
    *,
    statuses: tuple[str, ...] = ("new",),
    respect_quiet_hours: bool = True,
) -> int:
    """Sends trend suggestions still waiting for a decision (`FR-TG-10`) and marks new ones `sent`.

    Used after a scan, by `/trends`, and to deliver what quiet hours held back (`FR-TG-18`).
    """
    settings = load_settings(paths.config_file)
    marks = ",".join("?" for _ in statuses)
    rows = query_all(
        paths.db_file,
        f"SELECT * FROM suggestions WHERE status IN ({marks}) ORDER BY id ASC LIMIT ?",
        (*statuses, max(1, int(settings.telegram.max_trend_msgs_per_day))),
    )
    sent_count = 0
    for s_row in rows:
        t_row = (
            query_one(paths.db_file, "SELECT * FROM trend_items WHERE id = ?", (s_row["trend_item_id"],))
            if s_row.get("trend_item_id")
            else None
        )
        text, kb = build_trend_suggestion_message(s_row, t_row)
        sent = await send_text_async(
            paths, text, keyboard=kb, respect_quiet_hours=respect_quiet_hours, topic="trends"
        )
        if sent:
            sent_count += 1
            with get_conn(paths.db_file) as conn:
                conn.execute("UPDATE suggestions SET status = 'sent' WHERE id = ? AND status = 'new'", (s_row["id"],))
    return sent_count


def flush_deferred_notifications(paths: AppPaths) -> int:
    """Delivers what was held back (quiet hours, bot offline): finished videos never sent for approval
    and new trend suggestions (`FR-TG-18`). Called periodically from a worker thread."""
    settings = load_settings(paths.config_file)
    if not SecretsStore(paths.secrets_file).get("TELEGRAM_BOT_TOKEN") or not settings.telegram.allowed_chat_ids:
        return 0
    if is_quiet_hours(settings):
        return 0

    async def _flush() -> int:
        count = 0
        rows = query_all(
            paths.db_file,
            """
            SELECT id FROM videos
            WHERE status = 'pending_approval' AND tg_message_id IS NULL AND output_path IS NOT NULL
            ORDER BY id ASC LIMIT 10
            """,
        )
        for r in rows:
            if await notify_pending_async(paths, int(r["id"])):
                count += 1
        return count + await send_open_suggestions_async(paths)

    return asyncio.run(_flush())


async def notify_pending_async(paths: AppPaths, video_id: int) -> list[int]:
    """Sends a `pending_approval` video with the 6-button Round 2 control keyboard (`FR-TG-13`)."""
    secrets = SecretsStore(paths.secrets_file)
    token = secrets.get("TELEGRAM_BOT_TOKEN")
    settings = load_settings(paths.config_file)
    if not token or not settings.telegram.allowed_chat_ids:
        return []
    if is_quiet_hours(settings):
        logger.info("Deferred pending_approval video #%d notification during quiet hours", video_id)
        return []

    row = query_one(paths.db_file, "SELECT * FROM videos WHERE id = ?", (video_id,))
    if row is None or not row.get("output_path"):
        return []

    master_path = paths.media_dir / str(row["output_path"])
    if not master_path.exists():
        return []

    all_products = list_products(paths.db_file, include_hidden=True)
    product_map = {p["id"]: p["name"] for p in all_products}
    item = enrich_approval_video(paths.db_file, row, product_map)

    target_ids = set(default_target_account_ids(paths.db_file, video_id))
    acc_rows = query_all(
        paths.db_file,
        "SELECT id, name, platform FROM accounts WHERE enabled = 1 ORDER BY platform, id",
    )
    acc_names = [f"{a['name']} ({a['platform']})" for a in acc_rows if int(a["id"]) in target_ids]

    next_slot_str: str | None = None
    if target_ids:
        try:
            from datetime import datetime
            from zoneinfo import ZoneInfo

            from videocreator.posting.slots import next_slot

            first_acc_id = sorted(target_ids)[0]
            slot_iso = next_slot(paths.db_file, first_acc_id, config_file=paths.config_file)
            tz_local = ZoneInfo(settings.schedule.timezone or "Asia/Ho_Chi_Minh")
            dt_local = datetime.fromisoformat(slot_iso.replace("Z", "+00:00")).astimezone(tz_local)
            next_slot_str = dt_local.strftime("%d/%m %H:%M")
        except Exception as slot_exc:
            logger.debug("Could not compute next_slot_str for video #%d: %s", video_id, slot_exc)

    caption, kb_rows = build_approval_message(
        item, account_names=acc_names, next_slot_str=next_slot_str
    )
    video_to_send = ensure_telegram_preview_video(paths, master_path, video_id)
    keyboard = _to_inline_markup(kb_rows)

    from telegram import Bot

    sent_ids: list[int] = []
    async with Bot(token=token) as bot:
        for chat_id in settings.telegram.allowed_chat_ids:
            try:
                with video_to_send.open("rb") as vf:
                    msg = await bot.send_video(
                        chat_id=chat_id,
                        video=vf,
                        caption=caption,
                        reply_markup=keyboard,
                        message_thread_id=topic_thread_id(paths, int(chat_id), "approvals"),
                        read_timeout=120,
                        write_timeout=120,
                    )
                sent_ids.append(int(msg.message_id))
            except Exception as exc:
                logger.warning("Failed to send pending video #%d to chat %s: %s", video_id, chat_id, exc)

    if sent_ids:
        with get_conn(paths.db_file) as conn:
            conn.execute(
                "UPDATE videos SET tg_message_id = ? WHERE id = ?",
                (sent_ids[0], video_id),
            )
    return sent_ids


def notify_pending(paths: AppPaths, video_id: int) -> list[int]:
    """Triggers Telegram notification for `video_id` (no-op if bot token/chats are unset)."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(notify_pending_async(paths, video_id))
        return []
    except RuntimeError:
        return asyncio.run(notify_pending_async(paths, video_id))


class TelegramBotService:
    """Manages PTB v22 `Application` polling lifecycle inside FastAPI's lifespan."""

    def __init__(self, paths: AppPaths, secrets_store: SecretsStore) -> None:
        self.paths = paths
        self.secrets = secrets_store
        self.app: Any = None
        self.last_error: str | None = None

    async def start(self) -> bool:
        settings = load_settings(self.paths.config_file)
        if settings.role != "server":
            return False
        token = self.secrets.get("TELEGRAM_BOT_TOKEN")
        if not token:
            return False

        try:
            from telegram import BotCommand, Update
            from telegram.ext import (
                Application,
                CallbackQueryHandler,
                CommandHandler,
                ContextTypes,
                MessageHandler,
                filters,
            )

            async def _react(update: Update, emoji: str) -> None:
                if update.message:
                    try:
                        await update.message.set_reaction(emoji)
                    except Exception:
                        pass

            async def on_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
                if not update.message or not update.message.text:
                    return
                chat_id = update.effective_chat.id if update.effective_chat else None
                user = update.effective_user
                user_id = user.id if user else None
                user_name = (user.full_name or user.username or str(user_id)) if user else "user"

                parts = update.message.text.strip().split(maxsplit=1)
                cmd_name = parts[0].lstrip("/").split("@")[0].lower()
                cmd_args = parts[1] if len(parts) > 1 else ""

                await _react(update, "👀")
                ok = await run_command(update.message, chat_id, user_id, user_name, cmd_name, cmd_args)
                await _react(update, "👌" if ok else "👎")

            async def run_command(
                message: Any, chat_id: int | None, user_id: int | None, user_name: str, cmd_name: str, cmd_args: str = ""
            ) -> bool:
                """Runs one command and answers with a new message. Shared by slash commands and menu buttons."""
                if cmd_name in ("pending", "trends", "setup"):
                    cfg = load_settings(self.paths.config_file)
                    allowed, err_msg = check_two_layer_allowlist(chat_id, user_id, cfg)
                    if not allowed:
                        await message.reply_text(err_msg or "Không có quyền.")
                        return False
                if cmd_name == "pending":
                    pending = list_pending_approval_videos(self.paths.db_file)
                    if not pending:
                        await message.reply_text("Hiện không có video nào đang chờ duyệt.")
                    for v in pending:
                        await notify_pending_async(self.paths, int(v["id"]))
                    return True
                if cmd_name == "trends":
                    sent = await send_open_suggestions_async(
                        self.paths, statuses=("new", "sent"), respect_quiet_hours=False
                    )
                    if not sent:
                        await message.reply_text("Hiện không có đề xuất xu hướng nào chưa xử lý.")
                    return True
                if cmd_name == "setup":
                    await message.reply_text(await setup_topics(message.chat))
                    return True

                ok, reply_text, kb = execute_command(
                    self.paths,
                    chat_id=chat_id,
                    user_id=user_id,
                    user_name=user_name,
                    command=cmd_name,
                    args=cmd_args,
                )
                await message.reply_text(reply_text[:4096], reply_markup=_to_inline_markup(kb))
                return ok

            async def setup_topics(chat: Any) -> str:
                """`/setup` (`FR-TG-02`): creates one forum topic per area in a group with Topics enabled."""
                if not getattr(chat, "is_forum", False):
                    set_setting(self.paths.db_file, TOPICS_SETTING_KEY, "{}")
                    return "Nhóm này chưa bật Topics nên mọi tin được gửi chung. Bật Topics trong cài đặt nhóm, cho bot quyền quản lý chủ đề rồi chạy lại /setup."
                try:
                    saved = json.loads(get_setting(self.paths.db_file, TOPICS_SETTING_KEY) or "{}")
                except ValueError:
                    saved = {}
                threads: dict[str, int] = dict(saved.get("threads") or {}) if saved.get("chat_id") == chat.id else {}
                created: list[str] = []
                for key, label in TOPIC_NAMES:
                    if key in threads:
                        continue
                    topic = await self.app.bot.create_forum_topic(chat_id=chat.id, name=label)
                    threads[key] = int(topic.message_thread_id)
                    created.append(label)
                set_setting(
                    self.paths.db_file, TOPICS_SETTING_KEY, json.dumps({"chat_id": chat.id, "threads": threads})
                )
                if not created:
                    return "Các Topic đã được tạo từ trước; không tạo thêm."
                return "🗂 Đã tạo Topic: " + ", ".join(created) + ". Từ giờ tin được gửi vào đúng Topic."

            async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
                query = update.callback_query
                if query is None:
                    return
                chat_id = update.effective_chat.id if update.effective_chat else None
                user = query.from_user
                user_id = user.id if user else None
                user_name = (user.full_name or user.username or str(user_id)) if user else "user"
                data = query.data or ""
                if data.startswith("cmd:") and query.message:
                    # Menu buttons: the answer is a full message, not a 190-character popup.
                    await query.answer()
                    await run_command(query.message, chat_id, user_id, user_name, data.split(":", 1)[1])
                    return
                allowed, reply_msg, won, new_kb = route_callback(
                    self.paths,
                    chat_id=chat_id,
                    user_id=user_id,
                    user_name=user_name,
                    data=data,
                )
                await query.answer(reply_msg[:190], show_alert=not allowed)
                if allowed and query.message:
                    try:
                        if new_kb is not None:
                            await query.edit_message_reply_markup(
                                reply_markup=_to_inline_markup(new_kb)
                            )
                        elif won:
                            if query.message.caption is not None:
                                orig_caption = query.message.caption or ""
                                new_caption = f"{orig_caption}\n\n{reply_msg}"[:1020]
                                await query.edit_message_caption(
                                    caption=new_caption, reply_markup=None
                                )
                            elif query.message.text is not None:
                                orig_text = query.message.text or ""
                                new_text = f"{orig_text}\n\n{reply_msg}"[:4000]
                                await query.edit_message_text(
                                    text=new_text, reply_markup=None
                                )
                    except Exception:
                        pass

            async def on_text_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
                if not update.message or not update.message.text:
                    return
                chat_id = update.effective_chat.id if update.effective_chat else None
                user = update.effective_user
                user_id = user.id if user else None
                user_name = (user.full_name or user.username or str(user_id)) if user else "user"
                handled, response_text = handle_pending_reply_input(
                    self.paths,
                    chat_id=chat_id,
                    user_id=user_id,
                    user_name=user_name,
                    text=update.message.text,
                )
                if handled and response_text:
                    await update.message.reply_text(response_text)

            async def on_video_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
                if not update.message:
                    return
                chat_id = update.effective_chat.id if update.effective_chat else None
                user = update.effective_user
                user_id = user.id if user else None
                user_name = (user.full_name or user.username or str(user_id)) if user else "user"
                cfg = load_settings(self.paths.config_file)
                allowed, _err = check_two_layer_allowlist(chat_id, user_id, cfg)
                if not allowed:
                    return

                media_obj = update.message.video or update.message.document
                if media_obj is None:
                    return

                from videocreator.manual.tickets import TICKET_FILENAME_RE, fulfill_manual_ticket

                ticket_id: int | None = None
                if update.message.reply_to_message:
                    reply_mid = int(update.message.reply_to_message.message_id)
                    t_row = query_one(
                        self.paths.db_file,
                        "SELECT id FROM manual_tickets WHERE tg_message_id = ? AND status IN ('open', 'reminded')",
                        (reply_mid,),
                    )
                    if t_row:
                        ticket_id = int(t_row["id"])
                    else:
                        reply_txt = str(
                            update.message.reply_to_message.text
                            or update.message.reply_to_message.caption
                            or ""
                        )
                        import re as _re

                        m_rep = _re.search(r"#(\d+)", reply_txt)
                        if m_rep:
                            ticket_id = int(m_rep.group(1))

                if ticket_id is None:
                    fname = str(getattr(media_obj, "file_name", "") or update.message.caption or "")
                    m_fn = TICKET_FILENAME_RE.search(fname)
                    if m_fn:
                        ticket_id = int(m_fn.group(1))

                if ticket_id is None:
                    return

                tmp_file = self.paths.work_dir / f"tg_ticket_{ticket_id}.mp4"
                tmp_file.parent.mkdir(parents=True, exist_ok=True)
                try:
                    tg_file = await media_obj.get_file()
                    await tg_file.download_to_drive(custom_path=str(tmp_file))
                    _aid, sid = fulfill_manual_ticket(
                        self.paths,
                        ticket_id,
                        tmp_file,
                        actor=f"tg:{user_id}:{user_name}",
                    )
                    await update.message.reply_text(
                        f"✅ Đã nhận video phiếu việc tay #{ticket_id} và đưa vào kho cảnh phụ (Shot #{sid})."
                    )
                except Exception as exc:
                    await update.message.reply_text(
                        f"❌ Không nạp được video cho phiếu #{ticket_id}: {exc}"
                    )
                finally:
                    tmp_file.unlink(missing_ok=True)

            self.app = Application.builder().token(token).build()
            for cmd_name, _desc in BOT_COMMAND_SPECS:
                self.app.add_handler(CommandHandler(cmd_name, on_command))
            self.app.add_handler(CallbackQueryHandler(on_callback))
            self.app.add_handler(
                MessageHandler(filters.TEXT & ~filters.COMMAND, on_text_reply)
            )
            self.app.add_handler(
                MessageHandler(filters.VIDEO | filters.Document.VIDEO, on_video_reply)
            )

            await self.app.initialize()
            try:
                await self.app.bot.set_my_commands(
                    [BotCommand(c, d) for c, d in BOT_COMMAND_SPECS]
                )
            except Exception as cmd_exc:
                logger.debug("set_my_commands warning: %s", cmd_exc)

            await self.app.start()
            if self.app.updater:
                await self.app.updater.start_polling(drop_pending_updates=False)
            logger.info("Started Telegram Control Center bot polling")
            return True
        except Exception as exc:
            self.last_error = str(exc)
            logger.error("Failed to start Telegram bot (FastAPI continues running): %s", exc)
            self.app = None
            return False

    async def stop(self) -> None:
        if self.app is None:
            return
        try:
            if self.app.updater and self.app.updater.running:
                await self.app.updater.stop()
            if self.app.running:
                await self.app.stop()
            await self.app.shutdown()
            logger.info("Stopped Telegram bot cleanly")
        except Exception as exc:
            logger.warning("Error stopping Telegram bot: %s", exc)
        finally:
            self.app = None

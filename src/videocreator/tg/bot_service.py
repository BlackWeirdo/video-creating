"""Telegram approval & control center bot: polling lifecycle inside FastAPI's lifespan (Phase 06 & 16)."""
from __future__ import annotations

import logging
from typing import Any

from videocreator.config import load_settings
from videocreator.paths import AppPaths
from videocreator.secrets_store import SecretsStore
from videocreator.tg.bot_handlers import BotUpdateHandlers
from videocreator.tg.commands import BOT_COMMAND_SPECS

logger = logging.getLogger("videocreator.telegram")


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
            from telegram import BotCommand
            from telegram.ext import (
                Application,
                CallbackQueryHandler,
                CommandHandler,
                MessageHandler,
                filters,
            )

            handlers = BotUpdateHandlers(self.paths)
            self.app = Application.builder().token(token).build()
            for cmd_name, _desc in BOT_COMMAND_SPECS:
                self.app.add_handler(CommandHandler(cmd_name, handlers.on_command))
            self.app.add_handler(CallbackQueryHandler(handlers.on_callback))
            self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.on_text_reply))
            self.app.add_handler(
                MessageHandler(filters.VIDEO | filters.Document.VIDEO, handlers.on_video_reply)
            )

            await self.app.initialize()
            try:
                await self.app.bot.set_my_commands([BotCommand(c, d) for c, d in BOT_COMMAND_SPECS])
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

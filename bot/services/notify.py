"""Adminlarga, foydalanuvchilarga va tarix kanaliga xabar yuborish (xatolarni yutib)."""
from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramNotFound, TelegramRetryAfter

from ..config import Config
from ..db import repo
from .settings import SettingsService

log = logging.getLogger("notify")


class Notifier:
    def __init__(self, bot: Bot, cfg: Config, settings: SettingsService) -> None:
        self.bot = bot
        self.cfg = cfg
        self.settings = settings

    async def user(self, user_id: int, text: str, reply_markup=None, disable_web_page_preview: bool = True) -> bool:
        """Foydalanuvchiga xabar. Bot bloklangan bo'lsa is_active=False qilinadi."""
        try:
            await self.bot.send_message(
                user_id, text, reply_markup=reply_markup, disable_web_page_preview=disable_web_page_preview
            )
            return True
        except (TelegramForbiddenError, TelegramNotFound):
            await repo.set_user_active(user_id, False)
            return False
        except TelegramRetryAfter as e:
            log.warning("RetryAfter %s s (user %s)", e.retry_after, user_id)
            return False
        except TelegramAPIError as e:
            log.warning("Foydalanuvchiga yuborilmadi %s: %s", user_id, e)
            return False

    async def admins(self, text: str, reply_markup=None) -> None:
        for admin_id in self.cfg.admin_ids:
            try:
                await self.bot.send_message(admin_id, text, reply_markup=reply_markup, disable_web_page_preview=True)
            except TelegramAPIError as e:
                log.warning("Adminga yuborilmadi %s: %s", admin_id, e)

    async def admins_photo(self, photo_file_id: str, caption: str, reply_markup=None) -> None:
        for admin_id in self.cfg.admin_ids:
            try:
                await self.bot.send_photo(admin_id, photo_file_id, caption=caption, reply_markup=reply_markup)
            except TelegramAPIError as e:
                log.warning("Adminga rasm yuborilmadi %s: %s", admin_id, e)
                try:
                    await self.bot.send_message(admin_id, caption, reply_markup=reply_markup)
                except TelegramAPIError:
                    pass

    async def history_channel(self, text: str) -> None:
        channel = self.settings.get("history_channel").strip()
        if not channel:
            return
        chat_id: int | str = channel
        if channel.lstrip("-").isdigit():
            chat_id = int(channel)
        elif not channel.startswith("@"):
            chat_id = f"@{channel}"
        try:
            await self.bot.send_message(chat_id, text, disable_web_page_preview=True)
        except TelegramAPIError as e:
            log.warning("Tarix kanaliga yuborilmadi (%s): %s", channel, e)

    async def edit_user_message(self, user_id: int, message_id: int | None, text: str, reply_markup=None) -> None:
        if not message_id:
            return
        try:
            await self.bot.edit_message_text(text, chat_id=user_id, message_id=message_id, reply_markup=reply_markup)
        except TelegramAPIError:
            pass

"""Majburiy obuna kanallari: ro'yxat keshi va obunani tekshirish."""
from __future__ import annotations

import logging
import time

from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError

from ..db import repo
from ..db.models import Channel

log = logging.getLogger("channels")

CACHE_TTL = 120.0  # soniya — obuna natijasini shuncha vaqt eslab turamiz


class ChannelService:
    def __init__(self, bot: Bot) -> None:
        self.bot = bot
        self._channels: list[Channel] = []
        self._cache: dict[int, tuple[bool, float]] = {}

    async def reload(self) -> None:
        self._channels = await repo.list_channels()
        self._cache.clear()

    @property
    def channels(self) -> list[Channel]:
        return self._channels

    def forget(self, user_id: int) -> None:
        self._cache.pop(user_id, None)

    async def is_subscribed(self, user_id: int, force: bool = False) -> bool:
        """Barcha majburiy kanallarga obuna bo'lganmi. Kanal yo'q bo'lsa True."""
        if not self._channels:
            return True
        if not force:
            cached = self._cache.get(user_id)
            if cached and cached[1] > time.monotonic():
                return cached[0]

        ok = True
        for ch in self._channels:
            try:
                member = await self.bot.get_chat_member(ch.chat_id, user_id)
            except TelegramAPIError as e:
                # Bot kanalda admin emas yoki kanal topilmadi — foydalanuvchini qamab qo'ymaymiz
                log.warning("Obunani tekshirib bo'lmadi (%s): %s", ch.username, e)
                continue
            status = member.status
            if status in (ChatMemberStatus.LEFT, ChatMemberStatus.KICKED):
                ok = False
                break
            if status == ChatMemberStatus.RESTRICTED and not getattr(member, "is_member", True):
                ok = False
                break

        self._cache[user_id] = (ok, time.monotonic() + (CACHE_TTL if ok else 15.0))
        return ok

    async def resolve(self, username: str) -> tuple[int, str, str]:
        """@username -> (chat_id, username, title). Bot admin bo'lmasa ValueError."""
        username = username.strip().replace("https://t.me/", "").replace("t.me/", "").lstrip("@").strip("/")
        if not username:
            raise ValueError("Kanal username bo'sh.")
        try:
            chat = await self.bot.get_chat(f"@{username}")
        except TelegramAPIError as e:
            raise ValueError(f"Kanal topilmadi: @{username} ({e})") from e
        if chat.type not in ("channel", "supergroup", "group"):
            raise ValueError("Bu kanal yoki guruh emas.")
        try:
            me = await self.bot.get_chat_member(chat.id, (await self.bot.me()).id)
        except TelegramAPIError as e:
            raise ValueError(f"Bot kanalga kira olmadi. Botni kanalga admin qiling. ({e})") from e
        if me.status not in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR):
            raise ValueError("Bot bu kanalda admin emas. Avval botni kanalga admin qiling, keyin qayta urinib ko'ring.")
        return chat.id, (chat.username or username), (chat.title or username)

"""
Har bir xabar/callback oldidan:
  1. foydalanuvchini bazaga yozish (yoki yangilash) + referalni bog'lash
  2. bloklangan bo'lsa — to'xtatish
  3. majburiy kanallarga obunani tekshirish
  4. birinchi marta o'tganda taklif qiluvchiga "yangi referal" xabari
Adminlar uchun 2–3 tekshirilmaydi.
"""
from __future__ import annotations

import re
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message, TelegramObject

from .. import texts
from ..callbacks import SimpleCB
from ..db import repo
from ..keyboards.user import subscribe_kb

_REF_RE = re.compile(r"^/start(?:@\w+)?\s+ref_?(\d{3,20})\s*$", re.IGNORECASE)


def parse_referrer(text: str | None) -> int | None:
    if not text:
        return None
    m = _REF_RE.match(text.strip())
    return int(m.group(1)) if m else None


class AccessMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        # Bot faqat shaxsiy chatda ishlaydi (guruh/kanaldagi xabarlarga javob bermaydi)
        if isinstance(event, Message) and event.chat.type != "private":
            return None
        if isinstance(event, CallbackQuery) and event.message is not None:
            chat = getattr(event.message, "chat", None)
            if chat is not None and chat.type != "private":
                return None

        tg_user = data.get("event_from_user")
        if tg_user is None or tg_user.is_bot:
            return None

        cfg = data["cfg"]
        settings = data["settings"]
        channels = data["channels"]
        notifier = data["notifier"]

        referrer_id = None
        if isinstance(event, Message):
            referrer_id = parse_referrer(event.text)

        db_user, created = await repo.get_or_create_user(
            tg_user.id, tg_user.first_name or "", tg_user.username, referrer_id
        )
        data["db_user"] = db_user
        data["user_created"] = created
        is_admin = cfg.is_admin(tg_user.id)
        data["is_admin"] = is_admin

        if is_admin:
            return await handler(event, data)

        # ---- bloklangan ----
        if db_user.is_blocked:
            text = texts.blocked(settings.get("admin_username"))
            try:
                if isinstance(event, CallbackQuery):
                    await event.answer("🚫 Siz bloklangansiz", show_alert=True)
                elif isinstance(event, Message):
                    await event.answer(text)
            except TelegramAPIError:
                pass
            return None

        # ---- majburiy obuna ----
        if channels.channels:
            force = isinstance(event, CallbackQuery) and event.data == SimpleCB(action="check_sub").pack()
            subscribed = await channels.is_subscribed(tg_user.id, force=force)
            if not subscribed:
                kb = subscribe_kb(channels.channels)
                try:
                    if isinstance(event, CallbackQuery):
                        if force:
                            await event.answer(texts.SUB_NOT_YET, show_alert=True)
                        else:
                            await event.answer()
                            if event.message is not None:
                                await event.message.answer(texts.subscribe_required(), reply_markup=kb)
                    elif isinstance(event, Message):
                        await event.answer(texts.subscribe_required(), reply_markup=kb)
                except TelegramAPIError:
                    pass
                return None

        # ---- referal: birinchi marta to'liq o'tdi (obuna sharti bajarildi) ----
        if db_user.referrer_id and not db_user.ref_credited:
            if await repo.mark_ref_credited(db_user.id):
                db_user.ref_credited = True
                await notifier.user(db_user.referrer_id, texts.new_referral(db_user.first_name))

        return await handler(event, data)

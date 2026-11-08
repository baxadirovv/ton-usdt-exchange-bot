"""Handlerlar uchun yordamchi funksiyalar."""
from __future__ import annotations

import logging

from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import CallbackQuery, Message

log = logging.getLogger("helpers")


async def safe_edit(call: CallbackQuery, text: str, reply_markup=None) -> None:
    """Callback kelgan xabarni tahrirlaydi; iloji bo'lmasa yangi xabar yuboradi."""
    msg = call.message
    if isinstance(msg, Message):
        try:
            if msg.text is not None:
                await msg.edit_text(text, reply_markup=reply_markup, disable_web_page_preview=True)
                return
            if msg.caption is not None or msg.photo or msg.document:
                await msg.edit_caption(caption=text[:1024], reply_markup=reply_markup)
                return
        except TelegramBadRequest as e:
            if "message is not modified" in str(e).lower():
                return
        except TelegramAPIError:
            pass
    try:
        await call.bot.send_message(call.from_user.id, text, reply_markup=reply_markup, disable_web_page_preview=True)
    except TelegramAPIError as e:
        log.warning("safe_edit: yuborilmadi: %s", e)


async def safe_answer(call: CallbackQuery, text: str | None = None, show_alert: bool = False) -> None:
    try:
        await call.answer(text, show_alert=show_alert)
    except TelegramAPIError:
        pass


async def remove_markup(call: CallbackQuery) -> None:
    msg = call.message
    if isinstance(msg, Message):
        try:
            await msg.edit_reply_markup(reply_markup=None)
        except TelegramAPIError:
            pass

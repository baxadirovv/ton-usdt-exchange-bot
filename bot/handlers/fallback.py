"""Hech qaysi handler tutmagan xabar va tugmalar uchun javob (eng oxirgi router)."""
from __future__ import annotations

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from .. import texts
from ..helpers import remove_markup, safe_answer
from ..keyboards.user import cancel_kb, main_menu

router = Router(name="fallback")


@router.message()
async def unknown_message(message: Message, state: FSMContext, is_admin: bool = False) -> None:
    current = await state.get_state()
    if current is not None:
        # Biror jarayon ichida kutilmagan turdagi xabar (masalan matn o'rniga stiker)
        await message.answer(
            "⚠️ Kutilgan ma'lumot yuborilmadi. Iltimos, so'ralgan ma'lumotni yuboring yoki bekor qiling.",
            reply_markup=cancel_kb(),
        )
        return
    await message.answer(texts.UNKNOWN_INPUT, reply_markup=main_menu(is_admin))


@router.callback_query()
async def stale_callback(call: CallbackQuery) -> None:
    await safe_answer(call, "⌛️ Bu tugma eskirgan. Iltimos, menyudan qaytadan boshlang.", show_alert=True)
    await remove_markup(call)

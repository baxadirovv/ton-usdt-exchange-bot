"""✉️ Reklama yuborish."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ... import texts
from ...callbacks import AdmBroadcastCB
from ...config import Config
from ...db import repo
from ...helpers import safe_answer, safe_edit
from ...keyboards.admin import broadcast_confirm_kb
from ...keyboards.user import cancel_kb
from ...services.broadcast import BroadcastService
from ...states import AdminBroadcastState

router = Router(name="admin_broadcast")


def stop_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="⏹ To'xtatish", callback_data=AdmBroadcastCB(action="stop"))
    return b.as_markup()


@router.message(F.text == texts.BTN_A_BROADCAST)
async def a_broadcast(message: Message, state: FSMContext, broadcaster: BroadcastService, cfg: Config) -> None:
    await state.clear()
    if broadcaster.running:
        await message.answer("⏳ Hozir boshqa reklama yuborilmoqda. Tugashini kuting yoki to'xtating.", reply_markup=stop_kb())
        return
    await state.set_state(AdminBroadcastState.message)
    count = len(await repo.all_broadcast_user_ids())
    await message.answer(
        "✉️ <b>Reklama yuborish</b>\n\n"
        f"👥 Qabul qiluvchilar: <b>{count}</b> ta faol foydalanuvchi\n"
        f"⚡️ Tezlik: <b>{cfg.broadcast_per_minute}</b> ta/daqiqa\n\n"
        "Yubormoqchi bo'lgan xabaringizni yuboring (matn, rasm, video, fayl, ovoz — istalgan turdagi xabar):",
        reply_markup=cancel_kb(),
    )


@router.message(AdminBroadcastState.message)
async def a_broadcast_message(message: Message, state: FSMContext) -> None:
    await state.update_data(from_chat_id=message.chat.id, message_id=message.message_id)
    await state.set_state(AdminBroadcastState.confirm)
    await message.reply(
        "☝️ Shu xabar barcha foydalanuvchilarga yuboriladi.\n\n"
        "📤 <b>Forward</b> — xabar manbasi (kimdan) ko'rinadi\n"
        "📋 <b>Nusxa</b> — xabar bot nomidan, manbasiz yuboriladi\n\n"
        "Qanday yuboramiz?",
        reply_markup=broadcast_confirm_kb(),
    )


@router.callback_query(AdmBroadcastCB.filter(F.action == "stop"))
async def cb_broadcast_stop(call: CallbackQuery, broadcaster: BroadcastService) -> None:
    if broadcaster.stop():
        await safe_answer(call, "⏹ To'xtatilmoqda...")
    else:
        await safe_answer(call, "Hozir reklama yuborilmayapti.", show_alert=True)


@router.callback_query(AdminBroadcastState.confirm, AdmBroadcastCB.filter())
async def cb_broadcast_confirm(
    call: CallbackQuery,
    callback_data: AdmBroadcastCB,
    state: FSMContext,
    broadcaster: BroadcastService,
) -> None:
    if callback_data.action == "cancel":
        await state.clear()
        await safe_edit(call, texts.CANCELLED)
        await safe_answer(call)
        return

    data = await state.get_data()
    await state.clear()
    mode = "copy" if callback_data.action == "copy" else "forward"
    started = await broadcaster.start(
        admin_chat_id=call.from_user.id,
        from_chat_id=int(data["from_chat_id"]),
        message_id=int(data["message_id"]),
        mode=mode,
        stop_markup=stop_kb(),
    )
    if not started:
        await safe_answer(call, "⏳ Boshqa reklama yuborilmoqda.", show_alert=True)
        return
    await safe_edit(call, "🚀 Reklama yuborish boshlandi! Hisobot pastda yangilanib boradi.")
    await safe_answer(call)


@router.callback_query(AdmBroadcastCB.filter())
async def cb_broadcast_stale(call: CallbackQuery) -> None:
    await safe_answer(call, "⌛️ Bu tugma eskirgan. Reklamani qaytadan boshlang.", show_alert=True)

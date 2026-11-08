"""📢 Kanallar: qo'shish, tahrirlash (username o'zgartirish / o'chirish), ro'yxat."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ... import texts
from ...callbacks import AdmChanCB
from ...db import repo
from ...helpers import safe_answer, safe_edit
from ...keyboards.admin import channel_edit_kb, channels_menu_kb, channels_pick_kb
from ...keyboards.user import cancel_kb
from ...services.channels import ChannelService
from ...states import AdminChannelState
from ...utils import esc

router = Router(name="admin_channels")

MENU_TEXT = (
    "📢 <b>Majburiy obuna kanallari</b>\n\n"
    "Kanal qo'shilsa, foydalanuvchilar unga obuna bo'lmaguncha botdan foydalana olmaydi.\n"
    "⚠️ Bot kanalda <b>admin</b> bo'lishi shart."
)


def _list_text(channels) -> str:
    if not channels:
        return "📋 Kanallar ro'yxati bo'sh."
    lines = [f"{i}. {esc(ch.title)} — @{esc(ch.username.lstrip('@'))} (<code>{ch.chat_id}</code>)" for i, ch in enumerate(channels, 1)]
    return "📋 <b>Kanallar ro'yxati:</b>\n\n" + "\n".join(lines)


@router.message(F.text == texts.BTN_A_CHANNELS)
async def a_channels(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(MENU_TEXT, reply_markup=channels_menu_kb())


@router.callback_query(AdmChanCB.filter())
async def cb_channels(call: CallbackQuery, callback_data: AdmChanCB, state: FSMContext, channels: ChannelService) -> None:
    action = callback_data.action

    if action == "back":
        await state.clear()
        await safe_edit(call, MENU_TEXT, reply_markup=channels_menu_kb())
        await safe_answer(call)
        return

    if action == "add":
        await state.set_state(AdminChannelState.add_username)
        await safe_answer(call)
        if isinstance(call.message, Message):
            await call.message.answer(
                "➕ Kanal username ni yuboring (masalan: <code>@kanal</code>).\n"
                "Avval botni kanalga <b>admin</b> qilib qo'ying!",
                reply_markup=cancel_kb(),
            )
        return

    if action == "list":
        await safe_edit(call, _list_text(await repo.list_channels()), reply_markup=channels_menu_kb())
        await safe_answer(call)
        return

    if action == "edit":
        await state.clear()
        items = await repo.list_channels()
        if not items:
            await safe_answer(call, "Hali kanal qo'shilmagan.", show_alert=True)
            return
        await safe_edit(call, "✏️ Tahrirlash uchun kanalni tanlang:", reply_markup=channels_pick_kb(items))
        await safe_answer(call)
        return

    channel = await repo.get_channel(callback_data.channel_id)
    if channel is None:
        await safe_answer(call, "Kanal topilmadi.", show_alert=True)
        return

    if action == "pick":
        await safe_edit(
            call,
            f"📢 <b>{esc(channel.title)}</b>\n@{esc(channel.username.lstrip('@'))} (<code>{channel.chat_id}</code>)\n\nNima qilamiz?",
            reply_markup=channel_edit_kb(channel.id),
        )
        await safe_answer(call)
        return

    if action == "rename":
        await state.set_state(AdminChannelState.rename_username)
        await state.update_data(channel_id=channel.id)
        await safe_answer(call)
        if isinstance(call.message, Message):
            await call.message.answer("✏️ Kanalning yangi username ini yuboring (masalan: @yangi_kanal):", reply_markup=cancel_kb())
        return

    if action == "delete":
        await repo.delete_channel(channel.id)
        await channels.reload()
        await safe_edit(call, f"🗑 @{esc(channel.username.lstrip('@'))} o'chirildi.", reply_markup=channels_menu_kb())
        await safe_answer(call, "O'chirildi")
        return

    await safe_answer(call)


@router.message(AdminChannelState.add_username, F.text)
async def add_channel(message: Message, state: FSMContext, channels: ChannelService) -> None:
    try:
        chat_id, username, title = await channels.resolve(message.text or "")
    except ValueError as e:
        await message.answer(f"❌ {esc(str(e))}", reply_markup=cancel_kb())
        return
    await repo.add_channel(chat_id, username, title)
    await channels.reload()
    await state.clear()
    await message.answer(f"✅ Kanal qo'shildi: <b>{esc(title)}</b> (@{esc(username)})", reply_markup=channels_menu_kb())


@router.message(AdminChannelState.rename_username, F.text)
async def rename_channel(message: Message, state: FSMContext, channels: ChannelService) -> None:
    data = await state.get_data()
    try:
        chat_id, username, title = await channels.resolve(message.text or "")
    except ValueError as e:
        await message.answer(f"❌ {esc(str(e))}", reply_markup=cancel_kb())
        return
    updated = await repo.update_channel(int(data.get("channel_id", 0)), chat_id, username, title)
    await channels.reload()
    await state.clear()
    if updated is None:
        await message.answer("❌ Kanal topilmadi (o'chirilgan bo'lishi mumkin).", reply_markup=channels_menu_kb())
        return
    await message.answer(f"✅ Yangilandi: <b>{esc(title)}</b> (@{esc(username)})", reply_markup=channels_menu_kb())

"""/start, asosiy menyu, obuna tasdig'i, bekor qilish, admin panelga kirish."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, ChatMemberUpdated, Message

from .. import texts
from ..callbacks import SimpleCB
from ..db import repo
from ..helpers import safe_answer, safe_edit
from ..keyboards.admin import admin_menu
from ..keyboards.user import main_menu

router = Router(name="menu")


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, is_admin: bool) -> None:
    await state.clear()
    name = message.from_user.first_name if message.from_user else "do'stim"
    await message.answer(texts.start(name), reply_markup=main_menu(is_admin))


@router.message(Command("menu"))
@router.message(F.text == texts.BTN_A_BACK)
async def back_to_main(message: Message, state: FSMContext, is_admin: bool) -> None:
    await state.clear()
    await message.answer(texts.MAIN_MENU, reply_markup=main_menu(is_admin))


@router.message(Command("id"))
async def cmd_id(message: Message) -> None:
    await message.answer(f"🆔 Sizning Telegram ID: <code>{message.from_user.id}</code>")


@router.message(Command("admin"))
@router.message(F.text == texts.BTN_ADMIN)
async def admin_entry(message: Message, state: FSMContext, is_admin: bool) -> None:
    if not is_admin:
        await message.answer(texts.NOT_ADMIN)
        return
    await state.clear()
    await message.answer(texts.ADMIN_MENU, reply_markup=admin_menu())


@router.callback_query(SimpleCB.filter(F.action == "check_sub"))
async def cb_check_sub(call: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    # Bu yerga yetib kelgan bo'lsa — middleware obunani tasdiqlagan
    await safe_answer(call, texts.SUB_OK)
    if isinstance(call.message, Message):
        try:
            await call.message.delete()
        except TelegramAPIError:
            pass
    await state.clear()
    await call.bot.send_message(call.from_user.id, texts.MAIN_MENU, reply_markup=main_menu(is_admin))


@router.callback_query(SimpleCB.filter(F.action == "cancel"))
async def cb_cancel(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await safe_edit(call, texts.CANCELLED)
    await safe_answer(call)


@router.callback_query(SimpleCB.filter(F.action == "noop"))
async def cb_noop(call: CallbackQuery) -> None:
    await safe_answer(call)


@router.my_chat_member()
async def on_my_chat_member(event: ChatMemberUpdated) -> None:
    """Foydalanuvchi botni bloklasa/blokdan chiqarsa — is_active ni yangilaymiz."""
    if event.chat.type != "private":
        return
    status = event.new_chat_member.status
    if status == ChatMemberStatus.KICKED:
        await repo.set_user_active(event.chat.id, False)
    elif status == ChatMemberStatus.MEMBER:
        await repo.set_user_active(event.chat.id, True)

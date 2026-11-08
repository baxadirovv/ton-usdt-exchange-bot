"""💵 Balans va 💳 Balans to'ldirish (avto to'lov cheki)."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from .. import texts
from ..callbacks import SimpleCB, TopupCB
from ..config import Config
from ..db import repo
from ..db.models import User
from ..helpers import safe_answer, safe_edit
from ..keyboards.user import cancel_kb, topup_button_kb, topup_cancel_kb
from ..services.payments import PaymentService
from ..services.settings import SettingsService
from ..states import TopupState
from ..utils import fmt_card, parse_int

router = Router(name="balance")


@router.message(F.text == texts.BTN_BALANCE)
async def menu_balance(message: Message, state: FSMContext, cfg: Config, db_user: User) -> None:
    await state.clear()
    user = await repo.get_user(db_user.id) or db_user
    orders = await repo.user_orders_summary(user.id)
    ref_count = await repo.count_referrals(user.id)
    await message.answer(texts.balance_info(user, orders, ref_count, cfg.timezone), reply_markup=topup_button_kb())


async def _start_topup(target: Message, user_id: int, state: FSMContext, settings: SettingsService) -> None:
    if not settings.get("card_number").strip():
        await target.answer(texts.TOPUP_NOT_CONFIGURED)
        return
    active = await repo.get_active_payment(user_id)
    if active is not None:
        await target.answer(texts.topup_active_exists(active.amount), reply_markup=topup_cancel_kb(active.id))
        return
    await state.set_state(TopupState.amount)
    await target.answer(
        texts.topup_ask_amount(settings.get_int("topup_min", 10000), settings.get_int("topup_max", 10000000)),
        reply_markup=cancel_kb(),
    )


@router.message(F.text == texts.BTN_TOPUP)
async def menu_topup(message: Message, state: FSMContext, settings: SettingsService, db_user: User) -> None:
    await state.clear()
    await _start_topup(message, db_user.id, state, settings)


@router.callback_query(SimpleCB.filter(F.action == "topup"))
async def cb_topup(call: CallbackQuery, state: FSMContext, settings: SettingsService, db_user: User) -> None:
    await safe_answer(call)
    await state.clear()
    if isinstance(call.message, Message):
        await _start_topup(call.message, db_user.id, state, settings)


@router.message(TopupState.amount, F.text)
async def topup_amount(
    message: Message,
    state: FSMContext,
    cfg: Config,
    settings: SettingsService,
    payments: PaymentService,
    db_user: User,
) -> None:
    value = parse_int(message.text or "")
    min_amount = settings.get_int("topup_min", 10000)
    max_amount = settings.get_int("topup_max", 10000000)
    if value is None or value < min_amount or value > max_amount:
        await message.answer(texts.topup_range(min_amount, max_amount), reply_markup=cancel_kb())
        return

    active = await repo.get_active_payment(db_user.id)
    if active is not None:
        await state.clear()
        await message.answer(texts.topup_active_exists(active.amount), reply_markup=topup_cancel_kb(active.id))
        return

    payment = await payments.create_unique(db_user.id, value)
    await state.clear()
    sent = await message.answer(
        texts.topup_invoice(
            payment.id,
            payment.amount,
            payment.base_amount,
            fmt_card(settings.get("card_number")),
            settings.get("card_holder"),
            cfg.payment_timeout_minutes,
        ),
        reply_markup=topup_cancel_kb(payment.id),
    )
    await repo.set_payment_message(payment.id, sent.message_id)


@router.callback_query(TopupCB.filter(F.action == "cancel"))
async def cb_topup_cancel(call: CallbackQuery, callback_data: TopupCB, db_user: User) -> None:
    payment = await repo.cancel_payment(callback_data.payment_id, db_user.id)
    if payment is None:
        await safe_answer(call, "Bu to'lov allaqachon yakunlangan.", show_alert=True)
        return
    await safe_edit(call, texts.topup_invoice_cancelled_edit(payment.id, payment.amount))
    await safe_answer(call, texts.TOPUP_CANCELLED)

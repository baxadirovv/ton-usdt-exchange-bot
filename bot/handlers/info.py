"""📊 Kurs & Zaxira, 📃 Almashuv tarixi, 🔗 Referal, 📚 Qo'llanma, ☎️ Qo'llab-quvvatlash."""
from __future__ import annotations

import math

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from .. import texts
from ..callbacks import GuideCB, HistoryCB, SimpleCB
from ..config import Config
from ..db import repo
from ..db.models import User
from ..helpers import safe_answer, safe_edit
from ..keyboards.user import cancel_kb, guide_back_kb, guide_kb, history_kb, referral_kb
from ..services.market import MarketService
from ..services.settings import SettingsService
from ..services.ton import TonService
from ..states import HistoryState

router = Router(name="info")
PER_PAGE = 6


# ---------------- Kurs & zaxira ----------------
@router.message(F.text == texts.BTN_RATES)
async def menu_rates(message: Message, state: FSMContext, cfg: Config, market: MarketService) -> None:
    await state.clear()
    await message.answer(texts.rates_info(market, cfg.timezone))


# ---------------- Tarix ----------------
async def _history_text(user_id: int, page: int) -> tuple[str, int, int]:
    orders, total = await repo.list_user_orders(user_id, page, PER_PAGE)
    pages = max(1, math.ceil(total / PER_PAGE))
    if page >= pages:
        page = pages - 1
        orders, total = await repo.list_user_orders(user_id, page, PER_PAGE)
    if total == 0:
        return texts.HISTORY_EMPTY, 0, 1
    lines = "\n".join(texts.history_line(o) for o in orders)
    return f"{texts.history_page(page, pages)}\n\n{lines}", page, pages


@router.message(F.text == texts.BTN_HISTORY)
async def menu_history(message: Message, state: FSMContext, db_user: User) -> None:
    await state.clear()
    text, page, pages = await _history_text(db_user.id, 0)
    if text == texts.HISTORY_EMPTY:
        await message.answer(text)
        return
    await message.answer(text, reply_markup=history_kb(page, pages))


@router.callback_query(HistoryCB.filter())
async def cb_history_page(call: CallbackQuery, callback_data: HistoryCB, db_user: User) -> None:
    text, page, pages = await _history_text(db_user.id, max(0, callback_data.page))
    await safe_edit(call, text, reply_markup=None if text == texts.HISTORY_EMPTY else history_kb(page, pages))
    await safe_answer(call)


@router.callback_query(SimpleCB.filter(F.action == "hist_detail"))
async def cb_history_detail(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(HistoryState.order_id)
    await safe_answer(call)
    if isinstance(call.message, Message):
        await call.message.answer(texts.HISTORY_ASK_ID, reply_markup=cancel_kb())


@router.message(HistoryState.order_id, F.text)
async def history_detail(message: Message, state: FSMContext, cfg: Config, ton: TonService, db_user: User) -> None:
    raw = (message.text or "").strip().lstrip("#")
    if not raw.isdigit():
        await message.answer(texts.HISTORY_NOT_FOUND, reply_markup=cancel_kb())
        return
    order = await repo.get_user_order(db_user.id, int(raw))
    if order is None:
        await message.answer(texts.HISTORY_NOT_FOUND, reply_markup=cancel_kb())
        return
    await state.clear()
    link = ton.explorer_link(order.tx_hash) if order.tx_hash else None
    await message.answer(texts.order_details(order, cfg.timezone, link), disable_web_page_preview=True)


# ---------------- Referal ----------------
@router.message(F.text == texts.BTN_REFERRAL)
async def menu_referral(message: Message, state: FSMContext, settings: SettingsService, bot_username: str, db_user: User) -> None:
    await state.clear()
    user = await repo.get_user(db_user.id) or db_user
    count = await repo.count_referrals(user.id)
    link = f"https://t.me/{bot_username}?start=ref{user.id}"
    percent = settings.ref_percent
    await message.answer(
        texts.referral_info(link, percent, count, user.ref_earned),
        reply_markup=referral_kb(link, texts.referral_share_text(percent)),
        disable_web_page_preview=True,
    )


# ---------------- Qo'llanma ----------------
@router.message(F.text == texts.BTN_GUIDE)
async def menu_guide(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(texts.GUIDE_MENU, reply_markup=guide_kb())


@router.callback_query(GuideCB.filter())
async def cb_guide(call: CallbackQuery, callback_data: GuideCB) -> None:
    text = texts.GUIDES.get(callback_data.topic)
    if text is None:
        await safe_answer(call)
        return
    await safe_edit(call, text, reply_markup=guide_back_kb())
    await safe_answer(call)


@router.callback_query(SimpleCB.filter(F.action == "guide_menu"))
async def cb_guide_menu(call: CallbackQuery) -> None:
    await safe_edit(call, texts.GUIDE_MENU, reply_markup=guide_kb())
    await safe_answer(call)


# ---------------- Qo'llab-quvvatlash ----------------
@router.message(F.text == texts.BTN_SUPPORT)
async def menu_support(message: Message, state: FSMContext, settings: SettingsService) -> None:
    await state.clear()
    await message.answer(
        texts.support(settings.get("admin_username"), settings.get("news_channel"), settings.get("history_channel"))
    )

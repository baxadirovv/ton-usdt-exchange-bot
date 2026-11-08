"""🔄 Valyuta ayirboshlash — menyu va SOTIB OLISH oqimi (avtomatik yuborish)."""
from __future__ import annotations

import logging
import time
from decimal import ROUND_DOWN, Decimal

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from .. import texts
from ..callbacks import BuyConfirmCB, ExchangeCB, StockAlertCB
from ..db import repo
from ..db.models import User
from ..helpers import safe_answer, safe_edit
from ..keyboards.user import (
    buy_confirm_kb,
    cancel_kb,
    exchange_menu,
    stock_alert_kb,
    topup_button_kb,
)
from ..services.exchange import TransferWorker
from ..services.market import MarketService
from ..services.settings import SettingsService
from ..services.ton import TonService, parse_address
from ..states import BuyState
from ..utils import calc_total, fmt_amount, fmt_dec, parse_decimal, to_units

log = logging.getLogger("buy")
router = Router(name="exchange_buy")

QUOTE_TTL = 120  # tasdiqlash oynasida ko'rsatilgan narx shuncha soniya kafolatlanadi


@router.message(F.text == texts.BTN_EXCHANGE)
async def menu_exchange(message: Message, state: FSMContext, market: MarketService) -> None:
    await state.clear()
    await message.answer(
        texts.exchange_menu(
            market.buy_price("TON"), market.sell_price("TON"),
            market.buy_price("USDT"), market.sell_price("USDT"),
            market.has_rates(),
        ),
        reply_markup=exchange_menu(),
    )


def _affordable(balance: int, price: int) -> str:
    if price <= 0:
        return "0"
    value = (Decimal(balance) / Decimal(price)).quantize(Decimal("0.0001"), rounding=ROUND_DOWN)
    return fmt_dec(value, 4)


async def _ask_amount(target: Message, currency: str, settings: SettingsService, market: MarketService, user: User) -> None:
    price = market.buy_price(currency)
    await target.answer(
        texts.buy_ask_amount(
            currency,
            price,
            user.balance,
            _affordable(user.balance, price),
            fmt_amount(market.max_buy_units(currency), currency, 4),
            fmt_dec(settings.buy_min(currency), 6),
        ),
        reply_markup=cancel_kb(),
    )


@router.callback_query(ExchangeCB.filter(F.action == "buy"))
async def cb_buy_start(
    call: CallbackQuery,
    callback_data: ExchangeCB,
    state: FSMContext,
    settings: SettingsService,
    market: MarketService,
    db_user: User,
) -> None:
    currency = callback_data.currency
    if currency not in ("TON", "USDT"):
        await safe_answer(call)
        return
    if not settings.buy_enabled:
        await safe_answer(call, texts.BUY_DISABLED, show_alert=True)
        return
    if not market.has_rates():
        await safe_answer(call, texts.NO_RATES, show_alert=True)
        return
    if not market.is_available(currency):
        await safe_answer(call)
        if isinstance(call.message, Message):
            await call.message.answer(texts.out_of_stock(currency), reply_markup=stock_alert_kb(currency))
        return

    await state.clear()
    await state.set_state(BuyState.amount)
    await state.update_data(currency=currency)
    await safe_answer(call)
    if isinstance(call.message, Message):
        await _ask_amount(call.message, currency, settings, market, db_user)


@router.callback_query(StockAlertCB.filter())
async def cb_stock_alert(call: CallbackQuery, callback_data: StockAlertCB, db_user: User) -> None:
    currency = callback_data.currency
    if currency not in ("TON", "USDT"):
        await safe_answer(call)
        return
    is_new = await repo.add_stock_alert(db_user.id, currency)
    await safe_edit(call, texts.stock_alert_saved(currency) if is_new else texts.STOCK_ALERT_EXISTS)
    await safe_answer(call)


@router.message(BuyState.amount, F.text)
async def buy_amount(
    message: Message,
    state: FSMContext,
    settings: SettingsService,
    market: MarketService,
    db_user: User,
) -> None:
    data = await state.get_data()
    currency = data.get("currency", "TON")

    amount = parse_decimal(message.text or "")
    if amount is None:
        await message.answer(texts.INVALID_AMOUNT, reply_markup=cancel_kb())
        return
    if not settings.buy_enabled:
        await state.clear()
        await message.answer(texts.BUY_DISABLED)
        return
    if not market.has_rates():
        await state.clear()
        await message.answer(texts.NO_RATES)
        return

    min_amount = settings.buy_min(currency)
    if amount < min_amount:
        await message.answer(texts.amount_below_min(fmt_dec(min_amount, 6), currency), reply_markup=cancel_kb())
        return
    units = to_units(amount, currency)
    max_units = market.max_buy_units(currency)
    if units <= 0 or units > max_units:
        await message.answer(texts.amount_above_max(fmt_amount(max_units, currency, 4), currency), reply_markup=cancel_kb())
        return

    price = market.buy_price(currency)
    total = calc_total(amount, price)
    user = await repo.get_user(db_user.id) or db_user
    if total > user.balance:
        await message.answer(texts.not_enough_balance(total, user.balance), reply_markup=topup_button_kb())
        return

    await state.update_data(amount=str(amount), price=price, total=total)
    await state.set_state(BuyState.address)
    await message.answer(texts.buy_ask_address(currency), reply_markup=cancel_kb())


@router.message(BuyState.address, F.text)
async def buy_address(message: Message, state: FSMContext, ton: TonService, market: MarketService) -> None:
    address = parse_address(message.text or "")
    if address is None:
        await message.answer(texts.INVALID_ADDRESS, reply_markup=cancel_kb())
        return

    warning = ""
    try:
        info = await ton.get_address_info(address)
        if not info.is_active:
            warning = texts.ADDRESS_NOT_ACTIVE + "\n"
    except Exception as e:  # noqa: BLE001 — tarmoq xatosi bo'lsa tekshiruvsiz davom etamiz
        log.warning("Manzilni tekshirib bo'lmadi: %s", e)

    data = await state.get_data()
    currency = data["currency"]
    amount = Decimal(data["amount"])
    price = market.buy_price(currency) or int(data["price"])
    total = calc_total(amount, price)
    normalized = address.to_str(is_bounceable=False)

    await state.update_data(
        address=normalized,
        warning=warning,
        price=price,
        total=total,
        market_price=market.market_price(currency),
        quoted_at=time.time(),
    )
    await state.set_state(BuyState.confirm)
    await message.answer(
        texts.buy_confirm(currency, fmt_dec(amount, 6), price, total, normalized, warning),
        reply_markup=buy_confirm_kb(),
    )


@router.callback_query(BuyState.confirm, BuyConfirmCB.filter())
async def buy_confirm(
    call: CallbackQuery,
    callback_data: BuyConfirmCB,
    state: FSMContext,
    settings: SettingsService,
    market: MarketService,
    worker: TransferWorker,
    db_user: User,
) -> None:
    if callback_data.action != "ok":
        await state.clear()
        await safe_edit(call, texts.CANCELLED)
        await safe_answer(call)
        return

    data = await state.get_data()
    currency = data.get("currency")
    if currency not in ("TON", "USDT") or "amount" not in data or "address" not in data:
        await state.clear()
        await safe_edit(call, texts.CANCELLED)
        await safe_answer(call)
        return

    if not settings.buy_enabled:
        await state.clear()
        await safe_edit(call, texts.BUY_DISABLED)
        await safe_answer(call)
        return
    if not market.has_rates():
        await safe_answer(call, texts.NO_RATES, show_alert=True)
        return

    amount = Decimal(data["amount"])
    units = to_units(amount, currency)
    quoted_price = int(data["price"])
    if time.time() - float(data.get("quoted_at", 0)) <= QUOTE_TTL:
        # ko'rsatilgan narx hali amal qiladi
        price_now = quoted_price
        market_now = int(data.get("market_price") or market.market_price(currency))
    else:
        price_now = market.buy_price(currency)
        market_now = market.market_price(currency)
        if price_now != quoted_price:
            # narx muddati o'tdi va kurs o'zgardi — yangi narx bilan qayta tasdiqlash
            await state.update_data(
                price=price_now,
                total=calc_total(amount, price_now),
                market_price=market_now,
                quoted_at=time.time(),
            )
            await safe_edit(
                call,
                texts.buy_confirm(currency, fmt_dec(amount, 6), price_now, calc_total(amount, price_now), data["address"], data.get("warning", ""), changed=True),
                reply_markup=buy_confirm_kb(),
            )
            await safe_answer(call, "⚠️ Kurs yangilandi, qayta tasdiqlang")
            return
    total_now = calc_total(amount, price_now)

    max_units = market.max_buy_units(currency)
    if units > max_units:
        await state.clear()
        await safe_edit(call, texts.amount_above_max(fmt_amount(max_units, currency, 4), currency))
        await safe_answer(call)
        return

    order = await repo.create_buy_order_and_charge(
        user_id=db_user.id,
        currency=currency,
        amount_units=units,
        price=price_now,
        market_price=market_now,
        total_uzs=total_now,
        wallet_address=data["address"],
    )
    await state.clear()
    if order is None:
        user = await repo.get_user(db_user.id) or db_user
        await safe_edit(call, texts.not_enough_balance(total_now, user.balance), reply_markup=topup_button_kb())
        await safe_answer(call)
        return

    await safe_edit(call, texts.buy_processing(order.id))
    await safe_answer(call)
    await worker.enqueue(order)

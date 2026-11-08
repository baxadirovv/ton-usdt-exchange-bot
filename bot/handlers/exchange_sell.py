"""SOTISH oqimi: miqdor -> hamyonga yuborish (izoh bilan) -> skrinshot -> karta -> adminga ariza."""
from __future__ import annotations

import secrets
import time
from decimal import Decimal

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from .. import texts
from ..callbacks import ExchangeCB
from ..config import Config
from ..db import repo
from ..db.models import User
from ..helpers import safe_answer
from ..keyboards.admin import sell_review_kb
from ..keyboards.user import cancel_kb
from ..services.market import MarketService
from ..services.notify import Notifier
from ..services.settings import SettingsService
from ..services.ton import TonService
from ..states import SellState
from ..utils import calc_total, esc, fmt_card, fmt_crypto, fmt_dec, fmt_uzs, local_time, only_digits, parse_decimal, to_units

router = Router(name="exchange_sell")

SELL_QUOTE_TTL = 30 * 60  # sotish narxi shuncha soniya kafolatlanadi


def new_memo() -> str:
    return f"S{secrets.randbelow(900_000) + 100_000}"


@router.callback_query(ExchangeCB.filter(F.action == "sell"))
async def cb_sell_start(
    call: CallbackQuery,
    callback_data: ExchangeCB,
    state: FSMContext,
    settings: SettingsService,
    market: MarketService,
) -> None:
    currency = callback_data.currency
    if currency not in ("TON", "USDT"):
        await safe_answer(call)
        return
    if not market.has_rates():
        await safe_answer(call, texts.NO_RATES, show_alert=True)
        return

    await state.clear()
    await state.set_state(SellState.amount)
    await state.update_data(currency=currency)
    await safe_answer(call)
    if isinstance(call.message, Message):
        await call.message.answer(
            texts.sell_ask_amount(
                currency,
                market.sell_price(currency),
                fmt_dec(settings.sell_min(currency), 6),
                fmt_dec(settings.sell_max(currency), 6),
            ),
            reply_markup=cancel_kb(),
        )


@router.message(SellState.amount, F.text)
async def sell_amount(
    message: Message,
    state: FSMContext,
    settings: SettingsService,
    market: MarketService,
    ton: TonService,
) -> None:
    data = await state.get_data()
    currency = data.get("currency", "TON")

    amount = parse_decimal(message.text or "")
    if amount is None:
        await message.answer(texts.INVALID_AMOUNT, reply_markup=cancel_kb())
        return
    if not market.has_rates():
        await state.clear()
        await message.answer(texts.NO_RATES)
        return

    min_amount, max_amount = settings.sell_min(currency), settings.sell_max(currency)
    if amount < min_amount or amount > max_amount:
        await message.answer(
            texts.sell_amount_range(fmt_dec(min_amount, 6), fmt_dec(max_amount, 6), currency),
            reply_markup=cancel_kb(),
        )
        return

    price = market.sell_price(currency)
    total = calc_total(amount, price)
    address = settings.get("sell_wallet_address").strip() or ton.address
    memo = new_memo()

    await state.update_data(
        amount=str(amount), price=price, total=total, address=address, memo=memo, quoted_at=time.time()
    )
    await state.set_state(SellState.screenshot)
    await message.answer(
        texts.sell_send_to_wallet(currency, fmt_dec(amount, 6), address, total, memo),
        reply_markup=cancel_kb(),
    )


@router.message(SellState.screenshot, F.photo)
async def sell_screenshot(message: Message, state: FSMContext) -> None:
    await state.update_data(screenshot=message.photo[-1].file_id, screenshot_is_document=False)
    await state.set_state(SellState.card)
    await message.answer(texts.SELL_ASK_CARD, reply_markup=cancel_kb())


@router.message(SellState.screenshot, F.document)
async def sell_screenshot_document(message: Message, state: FSMContext) -> None:
    doc = message.document
    if doc and (doc.mime_type or "").startswith("image/"):
        await state.update_data(screenshot=doc.file_id, screenshot_is_document=True)
        await state.set_state(SellState.card)
        await message.answer(texts.SELL_ASK_CARD, reply_markup=cancel_kb())
        return
    await message.answer(texts.SELL_NEED_PHOTO, reply_markup=cancel_kb())


@router.message(SellState.screenshot)
async def sell_screenshot_other(message: Message) -> None:
    await message.answer(texts.SELL_NEED_PHOTO, reply_markup=cancel_kb())


@router.message(SellState.card, F.text)
async def sell_card(
    message: Message,
    state: FSMContext,
    cfg: Config,
    market: MarketService,
    notifier: Notifier,
    ton: TonService,
    db_user: User,
) -> None:
    digits = only_digits(message.text or "")
    if len(digits) < 16 or len(digits) > 19:
        await message.answer(texts.SELL_INVALID_CARD, reply_markup=cancel_kb())
        return

    data = await state.get_data()
    currency = data.get("currency", "TON")
    amount = Decimal(data["amount"])
    units = to_units(amount, currency)
    price = int(data["price"])
    repriced = False
    unverified_price = False

    # Narx kafolati muddati o'tgan bo'lsa — joriy va kafolatlangan narxning kichigi olinadi
    if time.time() - float(data.get("quoted_at", 0)) > SELL_QUOTE_TTL:
        current = market.sell_price(currency)
        if current <= 0:
            unverified_price = True  # joriy kurs yo'q — admin narxni o'zi tekshiradi
        elif current < price:
            price, repriced = current, True
    total = calc_total(amount, price)
    memo = data.get("memo") or new_memo()

    order = await repo.create_sell_order(
        user_id=db_user.id,
        currency=currency,
        amount_units=units,
        price=price,
        total_uzs=total,
        wallet_address=data["address"],
        screenshot_file_id=data.get("screenshot", ""),
        card_number=digits,
        memo=memo,
        note=(
            "narx yangilandi (kafolat muddati o'tgan)" if repriced
            else "DIQQAT: kafolat muddati o'tgan, joriy kurs yo'q — narxni tekshiring" if unverified_price
            else None
        ),
    )
    await state.clear()
    await message.answer(texts.sell_accepted(order.id, currency, total if repriced else None))

    uname = f"@{db_user.username}" if db_user.username else "—"
    quoted_at = data.get("quoted_at")
    quoted_line = ""
    if quoted_at:
        from datetime import datetime, timezone

        quoted_line = f"🕐 Narx belgilangan: {local_time(datetime.fromtimestamp(float(quoted_at), timezone.utc), cfg.timezone)}\n"
    caption = (
        f"📤 <b>Yangi SOTISH arizasi #{order.id}</b>\n\n"
        f"👤 {esc(db_user.first_name)} | {esc(uname)} | <code>{db_user.id}</code>\n"
        f"💱 {fmt_crypto(units, currency)} × {fmt_uzs(order.price)}"
        f"{' (narx yangilandi)' if repriced else ''}\n"
        f"💰 To'lanadi: <b>{fmt_uzs(order.total_uzs)}</b>\n"
        f"{'⚠️ <b>Narx kafolati tugagan va joriy kurs yo‘q — summani tekshiring!</b>' + chr(10) if unverified_price else ''}"
        f"💳 Karta: <code>{fmt_card(digits)}</code>\n"
        f"🏷 Izoh (memo): <code>{esc(memo)}</code>\n"
        f"{quoted_line}"
        f"📍 Hamyon: <code>{esc(data['address'])}</code>\n"
        f"🔗 {ton.address_link(data['address'])}\n\n"
        f"Hamyonga aynan <b>{fmt_crypto(units, currency)}</b> <code>{esc(memo)}</code> izohi bilan tushganini "
        "tekshirib, tasdiqlang yoki bekor qiling:"
    )
    screenshot = data.get("screenshot")
    kb = sell_review_kb(order.id)
    if screenshot and not data.get("screenshot_is_document"):
        await notifier.admins_photo(screenshot, caption, reply_markup=kb)
        return
    for admin_id in cfg.admin_ids:
        try:
            if screenshot:
                await message.bot.send_document(admin_id, screenshot, caption=caption, reply_markup=kb)
            else:
                await message.bot.send_message(admin_id, caption, reply_markup=kb, disable_web_page_preview=True)
        except TelegramAPIError:
            try:
                await message.bot.send_message(admin_id, caption, reply_markup=kb, disable_web_page_preview=True)
            except TelegramAPIError:
                pass

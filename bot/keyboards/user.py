"""Foydalanuvchi klaviaturalari."""
from __future__ import annotations

from urllib.parse import quote

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .. import texts
from ..callbacks import (
    BuyConfirmCB,
    ExchangeCB,
    GuideCB,
    HistoryCB,
    SimpleCB,
    StockAlertCB,
    TopupCB,
)


def main_menu(is_admin: bool) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text=texts.BTN_EXCHANGE)],
        [KeyboardButton(text=texts.BTN_BALANCE), KeyboardButton(text=texts.BTN_TOPUP)],
        [KeyboardButton(text=texts.BTN_RATES), KeyboardButton(text=texts.BTN_HISTORY)],
        [KeyboardButton(text=texts.BTN_REFERRAL), KeyboardButton(text=texts.BTN_GUIDE)],
        [KeyboardButton(text=texts.BTN_SUPPORT)],
    ]
    if is_admin:
        rows.append([KeyboardButton(text=texts.BTN_ADMIN)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=texts.CANCEL, callback_data=SimpleCB(action="cancel").pack())]]
    )


def exchange_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="💎 TonCoin (Gram) → Sotib olish", callback_data=ExchangeCB(action="buy", currency="TON"))
    b.button(text="💎 TonCoin (Gram) → Sotish", callback_data=ExchangeCB(action="sell", currency="TON"))
    b.button(text="💰 USDT (TON) → Sotib olish", callback_data=ExchangeCB(action="buy", currency="USDT"))
    b.button(text="💰 USDT (TON) → Sotish", callback_data=ExchangeCB(action="sell", currency="USDT"))
    b.adjust(1)
    return b.as_markup()


def stock_alert_kb(currency: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🔔 Kelganda xabar berilsin", callback_data=StockAlertCB(currency=currency))
    return b.as_markup()


def buy_confirm_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ Tasdiqlash", callback_data=BuyConfirmCB(action="ok"))
    b.button(text="❌ Bekor qilish", callback_data=BuyConfirmCB(action="no"))
    b.adjust(2)
    return b.as_markup()


def topup_button_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="💳 Balans to'ldirish", callback_data=SimpleCB(action="topup"))
    return b.as_markup()


def topup_cancel_kb(payment_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="❌ To'lovni bekor qilish", callback_data=TopupCB(action="cancel", payment_id=payment_id))
    return b.as_markup()


def history_kb(page: int, pages: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️ Oldingi", callback_data=HistoryCB(page=page - 1).pack()))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{pages}", callback_data=SimpleCB(action="noop").pack()))
    if page + 1 < pages:
        nav.append(InlineKeyboardButton(text="Keyingi ➡️", callback_data=HistoryCB(page=page + 1).pack()))
    b.row(*nav)
    b.row(InlineKeyboardButton(text="🔎 Batafsil ma'lumot", callback_data=SimpleCB(action="hist_detail").pack()))
    return b.as_markup()


def referral_kb(link: str, share_text: str) -> InlineKeyboardMarkup:
    share_url = f"https://t.me/share/url?url={quote(link, safe='')}&text={quote(share_text, safe='')}"
    b = InlineKeyboardBuilder()
    b.button(text="📤 Havolani ulashish", url=share_url)
    return b.as_markup()


def guide_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="💎 TonCoin sotib olish", callback_data=GuideCB(topic="buy_ton"))
    b.button(text="💎 TonCoin sotish", callback_data=GuideCB(topic="sell_ton"))
    b.button(text="💰 USDT sotib olish", callback_data=GuideCB(topic="buy_usdt"))
    b.button(text="💰 USDT sotish", callback_data=GuideCB(topic="sell_usdt"))
    b.adjust(2)
    return b.as_markup()


def guide_back_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=texts.BACK, callback_data=SimpleCB(action="guide_menu"))
    return b.as_markup()


def subscribe_kb(channels) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for ch in channels:
        b.row(InlineKeyboardButton(text=f"📢 {ch.title or ch.username}", url=f"https://t.me/{ch.username.lstrip('@')}"))
    b.row(InlineKeyboardButton(text="✅ Obuna bo'ldim", callback_data=SimpleCB(action="check_sub").pack()))
    return b.as_markup()

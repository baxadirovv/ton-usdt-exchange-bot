"""Admin panel klaviaturalari."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .. import texts
from ..callbacks import AdmBroadcastCB, AdmChanCB, AdmOrderCB, AdmSellCB, AdmSetCB, AdmUserCB


def admin_menu() -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text=texts.BTN_A_STATS), KeyboardButton(text=texts.BTN_A_SETTINGS)],
        [KeyboardButton(text=texts.BTN_A_PAYMENT), KeyboardButton(text=texts.BTN_A_USERS)],
        [KeyboardButton(text=texts.BTN_A_PRICES), KeyboardButton(text=texts.BTN_A_BROADCAST)],
        [KeyboardButton(text=texts.BTN_A_CHANNELS), KeyboardButton(text=texts.BTN_A_REFERRAL)],
        [KeyboardButton(text=texts.BTN_A_BACK)],
    ]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def sell_review_kb(order_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ Tasdiqlash", callback_data=AdmSellCB(action="ok", order_id=order_id))
    b.button(text="❌ Bekor qilish", callback_data=AdmSellCB(action="no", order_id=order_id))
    b.adjust(2)
    return b.as_markup()


def unknown_order_kb(order_id: int, can_recheck: bool = True) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if can_recheck:
        b.button(text="🔄 Qayta tekshirish (avtomatik)", callback_data=AdmOrderCB(action="recheck", order_id=order_id))
    b.button(text="✅ Yuborilgan (bajarildi)", callback_data=AdmOrderCB(action="done", order_id=order_id))
    b.button(text="↩️ Yuborilmagan (balansni qaytarish)", callback_data=AdmOrderCB(action="refund", order_id=order_id))
    b.adjust(1)
    return b.as_markup()


def settings_kb(buy_enabled: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="👤 Admin username", callback_data=AdmSetCB(key="admin_username"))
    b.button(text="📰 Yangiliklar kanali", callback_data=AdmSetCB(key="news_channel"))
    b.button(text="📜 Tarix kanali", callback_data=AdmSetCB(key="history_channel"))
    b.button(text="📥 Sotish uchun hamyon (qabul)", callback_data=AdmSetCB(key="sell_wallet_address"))
    b.button(
        text=("🟢 Sotuv holati: YOQILGAN" if buy_enabled else "🔴 Sotuv holati: O'CHIRILGAN") + " (almashtirish)",
        callback_data=AdmSetCB(key="toggle_buy"),
    )
    b.adjust(1)
    return b.as_markup()


def payment_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="💳 Karta raqami", callback_data=AdmSetCB(key="card_number"))
    b.button(text="👤 Karta egasi", callback_data=AdmSetCB(key="card_holder"))
    b.button(text="📉 Min to'ldirish", callback_data=AdmSetCB(key="topup_min"))
    b.button(text="📈 Max to'ldirish", callback_data=AdmSetCB(key="topup_max"))
    b.button(text="🔑 Yangi secret key yaratish", callback_data=AdmSetCB(key="new_secret"))
    b.button(text="🔗 Qabul qilish URL", callback_data=AdmSetCB(key="show_url"))
    b.adjust(2, 2, 1, 1)
    return b.as_markup()


def prices_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="💵 Ustama (so'm)", callback_data=AdmSetCB(key="markup_uzs"))
    b.button(text="💎 Min TON (sotib olish)", callback_data=AdmSetCB(key="buy_min_ton"))
    b.button(text="💰 Min USDT (sotib olish)", callback_data=AdmSetCB(key="buy_min_usdt"))
    b.button(text="💎 Min/Max TON (sotish)", callback_data=AdmSetCB(key="sell_range_ton"))
    b.button(text="💰 Min/Max USDT (sotish)", callback_data=AdmSetCB(key="sell_range_usdt"))
    b.button(text="🔄 Kurs va zaxirani hozir yangilash", callback_data=AdmSetCB(key="refresh_market"))
    b.adjust(1, 2, 2, 1)
    return b.as_markup()


def user_manage_kb(user_id: int, is_blocked: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="➕ Balansga pul qo'shish", callback_data=AdmUserCB(action="add", user_id=user_id))
    b.button(text="➖ Balansdan pul ayirish", callback_data=AdmUserCB(action="sub", user_id=user_id))
    if is_blocked:
        b.button(text="✅ Blokdan chiqarish", callback_data=AdmUserCB(action="unblock", user_id=user_id))
    else:
        b.button(text="🚫 Bloklash", callback_data=AdmUserCB(action="block", user_id=user_id))
    b.button(text="🔄 Yangilash", callback_data=AdmUserCB(action="refresh", user_id=user_id))
    b.adjust(2, 1, 1)
    return b.as_markup()


def broadcast_confirm_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="📤 Forward qilib yuborish", callback_data=AdmBroadcastCB(action="forward"))
    b.button(text="📋 Nusxa (manbasiz) yuborish", callback_data=AdmBroadcastCB(action="copy"))
    b.button(text="❌ Bekor qilish", callback_data=AdmBroadcastCB(action="cancel"))
    b.adjust(1)
    return b.as_markup()


def channels_menu_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="➕ Kanal qo'shish", callback_data=AdmChanCB(action="add"))
    b.button(text="✏️ Kanal tahrirlash", callback_data=AdmChanCB(action="edit"))
    b.button(text="📋 Kanallar ro'yxati", callback_data=AdmChanCB(action="list"))
    b.adjust(1)
    return b.as_markup()


def channels_pick_kb(channels) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for ch in channels:
        b.button(text=f"📢 {ch.title or ch.username} (@{ch.username.lstrip('@')})", callback_data=AdmChanCB(action="pick", channel_id=ch.id))
    b.button(text=texts.BACK, callback_data=AdmChanCB(action="back"))
    b.adjust(1)
    return b.as_markup()


def channel_edit_kb(channel_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✏️ Username o'zgartirish", callback_data=AdmChanCB(action="rename", channel_id=channel_id))
    b.button(text="🗑 O'chirish", callback_data=AdmChanCB(action="delete", channel_id=channel_id))
    b.button(text=texts.BACK, callback_data=AdmChanCB(action="edit"))
    b.adjust(1)
    return b.as_markup()


def referral_settings_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✏️ Referal foizini o'zgartirish", callback_data=AdmSetCB(key="ref_percent"))
    return b.as_markup()


def back_inline_kb(callback_data: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=texts.BACK, callback_data=callback_data)]])

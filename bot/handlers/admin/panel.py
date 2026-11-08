"""
Admin panel: 📊 Statistika, 🛠 Qo'shimcha sozlamalar, 💳 To'lov tizimi,
💰 Narxlar & Miqdor, 🔗 Referal sozlamasi — va ularning qiymatlarini o'zgartirish.
"""
from __future__ import annotations

from decimal import Decimal

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ... import texts
from ...callbacks import AdmSetCB
from ...config import Config
from ...db import repo
from ...helpers import safe_answer, safe_edit
from ...keyboards.admin import payment_kb, prices_kb, referral_settings_kb, settings_kb
from ...keyboards.user import cancel_kb
from ...services.channels import ChannelService
from ...services.market import MarketService
from ...services.settings import SettingsService
from ...services.ton import TonService, parse_address
from ...states import AdminSetState
from ...utils import esc, fmt_crypto, fmt_dec, fmt_uzs, local_time, only_digits, parse_decimal, parse_int

router = Router(name="admin_panel")


# =====================================================================
#  Ko'rinishlar (render)
# =====================================================================
async def render_stats(cfg: Config) -> str:
    u = await repo.users_stats()
    o = await repo.orders_stats()
    p = await repo.profit_stats()
    ref_total = await repo.ref_bonus_total()
    return (
        "📊 <b>Statistika</b>\n\n"
        f"👥 Foydalanuvchilar: <b>{u['total']}</b> (bugun: +{u['today_new']})\n"
        f"💰 Balanslar jami: <b>{fmt_uzs(u['balances'])}</b>\n"
        f"🚫 Bloklangan: {u['blocked']} | 🔕 Botni bloklagan: {u['inactive']}\n\n"
        f"📝 <b>Arizalar:</b> jami {o['total']}\n"
        f"├ ✅ Bajarilgan: {o['done']}\n"
        f"├ ⏳ Kutilmoqda: {o['waiting']}\n"
        f"└ ❌ Bekor qilingan: {o['cancelled']}\n\n"
        "💱 <b>Aylanma</b>\n"
        f"├ Sotildi (mijozlarga): {fmt_crypto(o['sold_ton'], 'TON')}, {fmt_crypto(o['sold_usdt'], 'USDT')} — {fmt_uzs(o['sold_uzs'])}\n"
        f"└ Olindi (mijozlardan): {fmt_crypto(o['bought_ton'], 'TON')}, {fmt_crypto(o['bought_usdt'], 'USDT')} — {fmt_uzs(o['bought_uzs'])}\n\n"
        f"📈 <b>Sof foyda: {fmt_uzs(p['total'])}</b> (bugun: {fmt_uzs(p['today'])})\n"
        f"🎁 Referal bonuslar: {fmt_uzs(ref_total)}"
    )


def render_settings(settings: SettingsService, ton: TonService) -> str:
    def show(v: str) -> str:
        return esc(v) if v.strip() else "—"

    sell_wallet = settings.get("sell_wallet_address").strip() or ton.address
    return (
        "🛠 <b>Qo'shimcha sozlamalar</b>\n\n"
        f"👤 Admin username: {show(settings.get('admin_username'))}\n"
        f"📰 Yangiliklar kanali: {show(settings.get('news_channel'))}\n"
        f"📜 Tarix kanali: {show(settings.get('history_channel'))}\n"
        f"📥 Sotish uchun hamyon: <code>{esc(sell_wallet)}</code>\n"
        f"🏦 Hot wallet (bot): <code>{esc(ton.address)}</code>\n"
        f"🛒 Sotuv holati: {'🟢 yoqilgan' if settings.buy_enabled else '🔴 o‘chirilgan'}\n\n"
        "ℹ️ Tarix kanali — har bir ayirboshlash haqida (faqat mijoz ismi bilan) post qilinadigan kanal. "
        "Bot u yerda admin bo'lishi kerak."
    )


def render_payment(settings: SettingsService, cfg: Config) -> str:
    card = settings.get("card_number")
    secret = settings.get("pay_secret_key")
    return (
        "💳 <b>To'lov tizimi</b>\n\n"
        f"💳 Karta: <code>{esc(card) if card else '—'}</code>\n"
        f"👤 Egasi: {esc(settings.get('card_holder')) or '—'}\n"
        f"📉 Min to'ldirish: {fmt_uzs(settings.get_int('topup_min'))}\n"
        f"📈 Max to'ldirish: {fmt_uzs(settings.get_int('topup_max'))}\n"
        f"⏳ Chek muddati: {cfg.payment_timeout_minutes} daqiqa\n"
        f"🔑 Secret key: <code>{esc(secret)}</code>\n\n"
        f"🔗 Qabul qilish URL:\n<code>{esc(cfg.public_url)}/pay</code>"
    )


def render_webhook_url(settings: SettingsService, cfg: Config) -> str:
    secret = settings.get("pay_secret_key")
    return (
        "🔗 <b>To'lov qabul qilish manzili</b>\n\n"
        "SMS/ilova shu manzilga so'rov yuborishi kerak (GET yoki POST):\n"
        f"<code>{esc(cfg.public_url)}/pay?miqdor={{miqdor}}&amp;method=CardXabarBot&amp;secret_key={esc(secret)}</code>\n\n"
        "Masalan:\n"
        f"<code>{esc(cfg.public_url)}/pay?miqdor=541545.00&amp;method=CardXabarBot&amp;secret_key={esc(secret)}</code>\n\n"
        "Bot kelgan summani faol cheklar orasidan topib, o'sha foydalanuvchi balansiga avtomatik qo'shadi."
    )


def render_prices(settings: SettingsService, market: MarketService, cfg: Config) -> str:
    updated = local_time(market.rates_updated_at, cfg.timezone) if market.rates_updated_at else "—"
    if market.has_rates():
        rates = (
            f"💎 TON: real {fmt_uzs(market.market_price('TON'))} → sotib olish <b>{fmt_uzs(market.buy_price('TON'))}</b>\n"
            f"💰 USDT: real {fmt_uzs(market.market_price('USDT'))} → sotib olish <b>{fmt_uzs(market.buy_price('USDT'))}</b>\n"
            f"🌍 1 USD = {fmt_uzs(int(market.usd_uzs))} | 1 TON = {market.ton_usd:.4f} $"
        )
    else:
        rates = "⚠️ Kurs hali yuklanmagan"
    reserve_err = f"\n⚠️ Zaxira xatosi: {esc(market.reserve_error)}" if market.reserve_error else ""
    if market.rates_error:
        rates += f"\n⚠️ Kurs xatosi: {esc(market.rates_error)}"
    if market.ton_usd > 0 and not market.rates_fresh():
        rates += "\n⛔️ Kurs 10 daqiqadan eski — savdo vaqtincha to'xtatilgan (manbalar ishlamayapti)"
    return (
        "💰 <b>Narxlar & Miqdor</b>\n\n"
        f"💵 Ustama: <b>{fmt_uzs(settings.markup)}</b> (TON va USDT uchun)\n\n"
        f"{rates}\n"
        f"🕐 Kurs yangilangan: {updated} ({esc(market.rates_source) or '—'})\n\n"
        "📦 <b>Zaxira (hot wallet)</b>\n"
        f"├ TON: {fmt_crypto(market.reserve['TON'], 'TON')} (sotishga: {fmt_crypto(market.max_buy_units('TON'), 'TON')})\n"
        f"└ USDT: {fmt_crypto(market.reserve['USDT'], 'USDT')}{reserve_err}\n\n"
        "📉 <b>Minimal sotib olish</b>\n"
        f"├ TON: {fmt_dec(settings.buy_min('TON'), 6)}\n"
        f"└ USDT: {fmt_dec(settings.buy_min('USDT'), 6)}\n"
        "📤 <b>Sotish (min — max)</b>\n"
        f"├ TON: {fmt_dec(settings.sell_min('TON'), 6)} — {fmt_dec(settings.sell_max('TON'), 6)}\n"
        f"└ USDT: {fmt_dec(settings.sell_min('USDT'), 6)} — {fmt_dec(settings.sell_max('USDT'), 6)}\n\n"
        "ℹ️ Maksimal sotib olish miqdori = hamyondagi zaxira. Kurs va zaxira har daqiqada yangilanadi."
    )


async def render_referral(settings: SettingsService) -> str:
    top = await repo.top_referrers(10)
    lines = []
    for i, (user, count) in enumerate(top, start=1):
        uname = f"@{user.username}" if user.username else f"id{user.id}"
        lines.append(f"{i}. {esc(user.first_name)} ({esc(uname)}) — {count} ta taklif, {fmt_uzs(user.ref_earned)}")
    body = "\n".join(lines) if lines else "Hali referal yo'q."
    return (
        "🔗 <b>Referal sozlamasi</b>\n\n"
        f"🎁 Referal foizi: <b>{settings.ref_percent:g}%</b> (har bir ayirboshlash summasidan)\n\n"
        f"🏆 <b>TOP-10 taklif qiluvchilar:</b>\n{body}"
    )


# =====================================================================
#  Menyu tugmalari
# =====================================================================
@router.message(F.text == texts.BTN_A_STATS)
async def a_stats(message: Message, state: FSMContext, cfg: Config) -> None:
    await state.clear()
    await message.answer(await render_stats(cfg))


@router.message(F.text == texts.BTN_A_SETTINGS)
async def a_settings(message: Message, state: FSMContext, settings: SettingsService, ton: TonService) -> None:
    await state.clear()
    await message.answer(render_settings(settings, ton), reply_markup=settings_kb(settings.buy_enabled))


@router.message(F.text == texts.BTN_A_PAYMENT)
async def a_payment(message: Message, state: FSMContext, settings: SettingsService, cfg: Config) -> None:
    await state.clear()
    await message.answer(render_payment(settings, cfg), reply_markup=payment_kb())


@router.message(F.text == texts.BTN_A_PRICES)
async def a_prices(message: Message, state: FSMContext, settings: SettingsService, market: MarketService, cfg: Config) -> None:
    await state.clear()
    await message.answer(render_prices(settings, market, cfg), reply_markup=prices_kb())


@router.message(F.text == texts.BTN_A_REFERRAL)
async def a_referral(message: Message, state: FSMContext, settings: SettingsService) -> None:
    await state.clear()
    await message.answer(await render_referral(settings), reply_markup=referral_settings_kb())


# =====================================================================
#  Sozlama qiymatini so'rash
# =====================================================================
PROMPTS: dict[str, tuple[str, str]] = {
    "admin_username": ("👤 Admin username ni yuboring (masalan: @admin):", "username"),
    "news_channel": ("📰 Yangiliklar kanali username ni yuboring (masalan: @kanal):", "username"),
    "history_channel": (
        "📜 Tarix kanali username (masalan: @kanal) yoki ID (-100...) ni yuboring.\n"
        "⚠️ Bot o'sha kanalda admin bo'lishi shart. O'chirish uchun '-' yuboring.",
        "channel",
    ),
    "sell_wallet_address": (
        "📥 Mijozlar sotganda valyuta yuboradigan TON hamyon manzilini yuboring.\n"
        "Hot wallet manzilini ishlatish uchun '-' yuboring.",
        "address",
    ),
    "card_number": ("💳 Karta raqamini yuboring (16 ta raqam):", "card"),
    "card_holder": ("👤 Karta egasining ismini yuboring:", "text"),
    "topup_min": ("📉 Minimal to'ldirish summasi (so'm):", "int"),
    "topup_max": ("📈 Maksimal to'ldirish summasi (so'm):", "int"),
    "markup_uzs": ("💵 Ustama summasini so'mda yuboring (masalan: 1000).\nBu ustama TON va USDT sotib olish narxiga qo'shiladi:", "int0"),
    "buy_min_ton": ("💎 Minimal TON sotib olish miqdori (masalan: 0.5):", "decimal"),
    "buy_min_usdt": ("💰 Minimal USDT sotib olish miqdori (masalan: 1):", "decimal"),
    "sell_range_ton": ("💎 TON sotish uchun min va max miqdorni bitta qatorda yuboring (masalan: 0.5 100):", "range"),
    "sell_range_usdt": ("💰 USDT sotish uchun min va max miqdorni bitta qatorda yuboring (masalan: 1 1000):", "range"),
    "ref_percent": ("🔗 Referal foizini yuboring (masalan: 2 yoki 2.5):", "percent"),
}

PANEL_OF_KEY: dict[str, str] = {
    "admin_username": "settings", "news_channel": "settings", "history_channel": "settings",
    "sell_wallet_address": "settings", "toggle_buy": "settings",
    "card_number": "payment", "card_holder": "payment", "topup_min": "payment", "topup_max": "payment",
    "new_secret": "payment", "show_url": "payment",
    "markup_uzs": "prices", "buy_min_ton": "prices", "buy_min_usdt": "prices",
    "sell_range_ton": "prices", "sell_range_usdt": "prices", "refresh_market": "prices",
    "ref_percent": "referral",
}


async def _show_panel(target: Message, panel: str, settings: SettingsService, cfg: Config, market: MarketService, ton: TonService) -> None:
    if panel == "settings":
        await target.answer(render_settings(settings, ton), reply_markup=settings_kb(settings.buy_enabled))
    elif panel == "payment":
        await target.answer(render_payment(settings, cfg), reply_markup=payment_kb())
    elif panel == "prices":
        await target.answer(render_prices(settings, market, cfg), reply_markup=prices_kb())
    elif panel == "referral":
        await target.answer(await render_referral(settings), reply_markup=referral_settings_kb())


@router.callback_query(AdmSetCB.filter())
async def cb_setting(
    call: CallbackQuery,
    callback_data: AdmSetCB,
    state: FSMContext,
    settings: SettingsService,
    cfg: Config,
    market: MarketService,
    ton: TonService,
) -> None:
    key = callback_data.key

    # ---- amallar ----
    if key == "toggle_buy":
        await settings.set("buy_enabled", not settings.buy_enabled)
        await safe_edit(call, render_settings(settings, ton), reply_markup=settings_kb(settings.buy_enabled))
        await safe_answer(call, "🟢 Sotuv yoqildi" if settings.buy_enabled else "🔴 Sotuv o'chirildi")
        return
    if key == "new_secret":
        await settings.regenerate_secret()
        await safe_edit(call, render_payment(settings, cfg), reply_markup=payment_kb())
        await safe_answer(call, "🔑 Yangi secret key yaratildi")
        return
    if key == "show_url":
        await safe_answer(call)
        if isinstance(call.message, Message):
            await call.message.answer(render_webhook_url(settings, cfg))
        return
    if key == "refresh_market":
        await safe_answer(call, "⏳ Yangilanmoqda...")
        await market.refresh_all(force=True)
        await safe_edit(call, render_prices(settings, market, cfg), reply_markup=prices_kb())
        return

    prompt = PROMPTS.get(key)
    if prompt is None:
        await safe_answer(call)
        return

    await state.set_state(AdminSetState.value)
    await state.update_data(key=key)
    await safe_answer(call)
    if isinstance(call.message, Message):
        await call.message.answer(prompt[0], reply_markup=cancel_kb())


@router.message(AdminSetState.value, F.text)
async def set_value(
    message: Message,
    state: FSMContext,
    settings: SettingsService,
    cfg: Config,
    market: MarketService,
    ton: TonService,
    channels: ChannelService,
) -> None:
    data = await state.get_data()
    key = data.get("key", "")
    prompt = PROMPTS.get(key)
    if prompt is None:
        await state.clear()
        await message.answer(texts.CANCELLED)
        return

    kind = prompt[1]
    raw = (message.text or "").strip()
    error: str | None = None

    try:
        if kind == "username":
            value = raw.replace("https://t.me/", "").replace("t.me/", "").lstrip("@").strip("/")
            if value == "-":
                value = ""
            if value and not value.replace("_", "").isalnum():
                error = "❌ Username noto'g'ri. Masalan: @admin"
            else:
                await settings.set(key, f"@{value}" if value else "")

        elif kind == "channel":
            if raw == "-":
                await settings.set(key, "")
            elif raw.lstrip("-").isdigit():
                try:
                    chat = await message.bot.get_chat(int(raw))
                    await settings.set(key, str(chat.id))
                except TelegramAPIError as e:
                    error = f"❌ Kanal topilmadi yoki bot u yerda yo'q: {e}"
            else:
                try:
                    chat_id, username, _title = await channels.resolve(raw)
                    await settings.set(key, f"@{username}")
                except ValueError as e:
                    error = f"❌ {e}"

        elif kind == "address":
            if raw == "-":
                await settings.set(key, "")
            else:
                addr = parse_address(raw)
                if addr is None:
                    error = texts.INVALID_ADDRESS
                else:
                    await settings.set(key, addr.to_str(is_bounceable=False))

        elif kind == "card":
            digits = only_digits(raw)
            if len(digits) < 16 or len(digits) > 19:
                error = "❌ Karta raqami 16 ta raqamdan iborat bo'lishi kerak."
            else:
                await settings.set(key, digits)

        elif kind == "text":
            if not raw:
                error = "❌ Bo'sh bo'lishi mumkin emas."
            else:
                await settings.set(key, raw[:64])

        elif kind in ("int", "int0"):
            value = parse_int(raw)
            if value is None or (kind == "int" and value <= 0):
                error = "❌ Faqat musbat butun son kiriting (masalan: 10000)."
            else:
                await settings.set(key, value)

        elif kind == "decimal":
            value = parse_decimal(raw)
            if value is None:
                error = texts.INVALID_AMOUNT
            else:
                await settings.set(key, fmt_dec(value, 6))

        elif kind == "range":
            parts = raw.replace(",", ".").replace("-", " ").split()
            if len(parts) != 2 or parse_decimal(parts[0]) is None or parse_decimal(parts[1]) is None:
                error = "❌ Ikkita son kiriting: min va max (masalan: 0.5 100)."
            else:
                lo, hi = parse_decimal(parts[0]), parse_decimal(parts[1])
                assert lo is not None and hi is not None
                if lo >= hi:
                    error = "❌ Min max dan kichik bo'lishi kerak."
                else:
                    cur = "ton" if key.endswith("_ton") else "usdt"
                    await settings.set(f"sell_min_{cur}", fmt_dec(lo, 6))
                    await settings.set(f"sell_max_{cur}", fmt_dec(hi, 6))

        elif kind == "percent":
            value = Decimal(0) if raw.strip() in ("0", "0.0", "0,0") else parse_decimal(raw)
            if value is None or value > Decimal(100):
                error = "❌ 0 dan 100 gacha son kiriting (masalan: 2)."
            else:
                await settings.set(key, fmt_dec(value, 2))
    except Exception as e:  # noqa: BLE001
        error = f"❌ Xatolik: {esc(str(e))}"

    if error:
        await message.answer(error, reply_markup=cancel_kb())
        return

    await state.clear()
    await message.answer("✅ Saqlandi.")
    await _show_panel(message, PANEL_OF_KEY.get(key, "settings"), settings, cfg, market, ton)

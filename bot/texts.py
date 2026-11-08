"""Botdagi barcha matnlar (o'zbek tilida, HTML formatda)."""
from __future__ import annotations

from .utils import esc, fmt_amount, fmt_crypto, fmt_uzs

# ---------------- Asosiy menyu tugmalari ----------------
BTN_EXCHANGE = "🔄 Valyuta Ayirboshlash"
BTN_BALANCE = "💵 Balans"
BTN_TOPUP = "💳 Balans to'ldirish"
BTN_RATES = "📊 Kurs & Zaxira"
BTN_HISTORY = "📃 Almashuv tarixi"
BTN_REFERRAL = "🔗 Referal bonus"
BTN_GUIDE = "📚 Qo'llanma"
BTN_SUPPORT = "☎️ Qo'llab-quvvatlash"
BTN_ADMIN = "🎛 Admin panel"

# ---------------- Admin panel tugmalari ----------------
BTN_A_STATS = "📊 Statistika"
BTN_A_SETTINGS = "🛠 Qo'shimcha sozlamalar"
BTN_A_PAYMENT = "💳 To'lov tizimi"
BTN_A_USERS = "⚙️ User boshqaruv"
BTN_A_PRICES = "💰 Narxlar & Miqdor"
BTN_A_BROADCAST = "✉️ Reklama yuborish"
BTN_A_CHANNELS = "📢 Kanallar"
BTN_A_REFERRAL = "🔗 Referal sozlamasi"
BTN_A_BACK = "🔙 Asosiy menyu"

MENU_BUTTONS = {
    BTN_EXCHANGE, BTN_BALANCE, BTN_TOPUP, BTN_RATES, BTN_HISTORY,
    BTN_REFERRAL, BTN_GUIDE, BTN_SUPPORT, BTN_ADMIN,
    BTN_A_STATS, BTN_A_SETTINGS, BTN_A_PAYMENT, BTN_A_USERS, BTN_A_PRICES,
    BTN_A_BROADCAST, BTN_A_CHANNELS, BTN_A_REFERRAL, BTN_A_BACK,
}

CANCEL = "❌ Bekor qilish"
BACK = "🔙 Orqaga"

STATUS_TEXT = {
    "processing": "⏳ Navbatda",
    "sending": "⏳ Yuborilmoqda",
    "done": "✅ Bajarildi",
    "failed": "❌ Bajarilmadi (balans qaytarildi)",
    "unknown": "❓ Admin tekshirmoqda",
    "pending": "🕐 Tekshirilmoqda",
    "approved": "✅ Tasdiqlandi",
    "cancelled": "❌ Bekor qilindi",
}

TYPE_TEXT = {"buy": "📥 Sotib olish", "sell": "📤 Sotish"}


# ---------------- Umumiy ----------------
def start(name: str) -> str:
    return (
        f"👋 Assalomu alaykum, <b>{esc(name)}</b>!\n\n"
        "🤖 Bu bot orqali <b>TonCoin (Gram)</b> va <b>USDT (TON)</b> ni "
        "tez, qulay va avtomatik tarzda sotib olishingiz yoki sotishingiz mumkin.\n\n"
        "Quyidagi menyudan kerakli bo'limni tanlang 👇"
    )


MAIN_MENU = "🏠 Asosiy menyu:"
ADMIN_MENU = "🎛 <b>Admin panel</b>\nKerakli bo'limni tanlang:"
CANCELLED = "❌ Amal bekor qilindi."
NOT_ADMIN = "⛔️ Bu bo'lim faqat adminlar uchun."
UNKNOWN_INPUT = "🤔 Tushunarsiz buyruq. Iltimos, menyudagi tugmalardan foydalaning."


def blocked(admin_username: str) -> str:
    admin = f"@{admin_username.lstrip('@')}" if admin_username else "admin"
    return (
        "🚫 <b>Siz bloklangansiz.</b>\n\n"
        f"Agar bu xato deb hisoblasangiz, adminga ariza yuborishingiz mumkin: {esc(admin)}"
    )


def subscribe_required() -> str:
    return (
        "📢 <b>Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling:</b>\n\n"
        "Obuna bo'lgach, <b>✅ Obuna bo'ldim</b> tugmasini bosing."
    )


SUB_NOT_YET = "❌ Siz hali barcha kanallarga obuna bo'lmadingiz!"
SUB_OK = "✅ Rahmat! Obuna tasdiqlandi."


# ---------------- Ayirboshlash ----------------
def exchange_menu(ton_buy: int, ton_sell: int, usdt_buy: int, usdt_sell: int, has_rates: bool) -> str:
    if not has_rates:
        rates = "⚠️ Kurs hozircha yuklanmadi, birozdan so'ng urinib ko'ring."
    else:
        rates = (
            f"💎 <b>TON</b>: sotib olish <b>{fmt_uzs(ton_buy)}</b> | sotish <b>{fmt_uzs(ton_sell)}</b>\n"
            f"💰 <b>USDT</b>: sotib olish <b>{fmt_uzs(usdt_buy)}</b> | sotish <b>{fmt_uzs(usdt_sell)}</b>"
        )
    return f"📊 <b>Joriy kurslar:</b>\n{rates}\n\n🔄 Ayirboshlash uslubini tanlang:"


BUY_DISABLED = "⛔️ Sotib olish hozircha faol emas. Keyinroq urinib ko'ring."
NO_RATES = "⚠️ Kurs hozircha mavjud emas. Birozdan so'ng qayta urinib ko'ring."


def out_of_stock(currency: str) -> str:
    name = "TonCoin" if currency == "TON" else "USDT"
    return f"😔 Botda hozircha <b>{name}</b> qolmagan. Keyinroq urinib ko'ring.\n\nZaxira kelganda xabar olishni xohlaysizmi?"


def stock_alert_saved(currency: str) -> str:
    name = "TonCoin" if currency == "TON" else "USDT"
    return f"🔔 Ushbu valyuta ({name}) yana kelganda sizga xabar beriladi."


STOCK_ALERT_EXISTS = "🔔 Siz allaqachon ro'yxatdasiz, kelganda xabar beramiz."


def stock_arrived(currency: str, reserve_units: int, price: int) -> str:
    name = "TonCoin" if currency == "TON" else "USDT"
    return (
        f"🔔 <b>{name} yana keldi botga!</b>\n\n"
        f"📦 Miqdori: <b>{fmt_crypto(reserve_units, currency)}</b>\n"
        f"💵 Kurs: <b>{fmt_uzs(price)}</b>"
    )


def buy_ask_amount(currency: str, price: int, balance: int, affordable: str, max_amount: str, min_amount: str) -> str:
    name = "TonCoin (Gram)" if currency == "TON" else "USDT (TON)"
    return (
        f"📥 <b>{name} sotib olish</b>\n\n"
        f"💵 Narx: <b>{fmt_uzs(price)}</b> (1 {currency})\n"
        f"💰 Balansingiz: <b>{fmt_uzs(balance)}</b>\n"
        f"🧮 Balansingizga yetadi: <b>{affordable} {currency}</b>\n"
        f"📦 Maksimal: <b>{max_amount} {currency}</b>\n"
        f"📉 Minimal: <b>{min_amount} {currency}</b>\n\n"
        f"Nechta {currency} sotib olasiz? Miqdorni yozing (masalan: 1.5)"
    )


INVALID_AMOUNT = "❌ Noto'g'ri miqdor. Faqat son kiriting (masalan: 1.5)"


def amount_below_min(min_amount: str, currency: str) -> str:
    return f"❌ Minimal miqdor: <b>{min_amount} {currency}</b>. Kattaroq miqdor kiriting."


def amount_above_max(max_amount: str, currency: str) -> str:
    return f"❌ Hozirda maksimal <b>{max_amount} {currency}</b> sotib olish mumkin (zaxira shuncha)."


def not_enough_balance(total: int, balance: int) -> str:
    return (
        f"❌ Balansingiz yetarli emas.\n\n"
        f"💰 Kerak: <b>{fmt_uzs(total)}</b>\n"
        f"💳 Balansingiz: <b>{fmt_uzs(balance)}</b>\n\n"
        "Avval balansni to'ldiring 👇"
    )


def buy_ask_address(currency: str) -> str:
    network_note = "\n⚠️ Faqat <b>TON tarmog'idagi</b> USDT manzili (TRC20/ERC20 emas!)" if currency == "USDT" else ""
    return (
        f"📍 <b>{currency} qabul qiladigan hamyon manzilingizni yuboring</b>\n\n"
        "Masalan: <code>UQD...</code> yoki <code>EQD...</code>\n"
        "(Tonkeeper, MyTonWallet, Telegram Wallet va boshqa TON hamyonlari)"
        f"{network_note}\n"
        "⚠️ Memo (izoh) talab qiladigan birja manzillarini kiritmang."
    )


INVALID_ADDRESS = "❌ Hamyon manzili noto'g'ri. TON hamyon manzilini to'g'ri nusxalab yuboring."
ADDRESS_NOT_ACTIVE = (
    "⚠️ <b>Diqqat!</b> Bu hamyon tarmoqda hali faollashtirilmagan (tranzaksiyasi yo'q).\n"
    "Manzil to'g'riligiga ishonchingiz komil bo'lsa davom eting."
)


def buy_confirm(currency: str, amount: str, price: int, total: int, address: str, warning: str = "", changed: bool = False) -> str:
    head = "⚠️ <b>Kurs yangilandi! Qayta tasdiqlang.</b>\n\n" if changed else ""
    return (
        f"{head}📋 <b>Ma'lumotlarni tasdiqlang:</b>\n\n"
        f"💱 Valyuta: <b>{currency}</b>\n"
        f"🔢 Miqdor: <b>{amount} {currency}</b>\n"
        f"💵 Narx: <b>{fmt_uzs(price)}</b>\n"
        f"💰 Jami: <b>{fmt_uzs(total)}</b>\n"
        f"📍 Hamyon: <code>{esc(address)}</code>\n"
        f"{warning}\n"
        "⏳ Narx 2 daqiqa davomida amal qiladi.\n"
        "Tasdiqlaysizmi?"
    )


def buy_processing(order_id: int) -> str:
    return f"⏳ <b>#{order_id}</b> raqamli so'rovingiz qabul qilindi. Valyuta yuborilmoqda, biroz kuting..."


def buy_done(order_id: int, amount_units: int, currency: str, link: str) -> str:
    return (
        f"✅ <b>#{order_id}</b> raqamli so'rovingiz bajarildi!\n\n"
        f"Siz belgilagan hamyonga <b>{fmt_amount(amount_units, currency)} ta {currency}</b> yuborildi!\n"
        f"🔗 <a href=\"{esc(link)}\">Tranzaksiyani ko'rish</a>"
    )


def buy_failed(order_id: int) -> str:
    return (
        f"❌ <b>#{order_id}</b> raqamli so'rovni bajarib bo'lmadi.\n"
        "Pul balansingizga qaytarildi. Birozdan so'ng qayta urinib ko'ring yoki adminga murojaat qiling."
    )


def buy_checking(order_id: int) -> str:
    return (
        f"⏳ <b>#{order_id}</b> so'rovingiz bo'yicha tranzaksiya tekshirilmoqda.\n"
        "Admin tekshirib, tez orada natija haqida xabar beradi."
    )


def buy_resolved_refund(order_id: int, total: int) -> str:
    return (
        f"↩️ <b>#{order_id}</b> so'rovingiz bajarilmadi. <b>{fmt_uzs(total)}</b> balansingizga qaytarildi."
    )


# ---------------- Sotish ----------------
def sell_ask_amount(currency: str, price: int, min_amount: str, max_amount: str) -> str:
    name = "TonCoin (Gram)" if currency == "TON" else "USDT (TON)"
    return (
        f"📤 <b>{name} sotish</b>\n\n"
        f"💵 Bot sizdan sotib olish kursi: <b>{fmt_uzs(price)}</b>\n"
        f"📉 Minimal: <b>{min_amount} {currency}</b>\n"
        f"📈 Maksimal: <b>{max_amount} {currency}</b>\n\n"
        f"Nechta {currency} sotmoqchisiz?"
    )


def sell_amount_range(min_amount: str, max_amount: str, currency: str) -> str:
    return f"❌ Miqdor <b>{min_amount}</b> dan <b>{max_amount}</b> {currency} gacha bo'lishi kerak."


def sell_send_to_wallet(currency: str, amount: str, address: str, total: int, memo: str) -> str:
    return (
        f"📍 Quyidagi hamyonga aynan <b>{amount} {currency}</b> yuboring:\n\n"
        f"<code>{esc(address)}</code>\n\n"
        f"🏷 O'tkazma izohiga (comment / memo) albatta shuni yozing: <code>{esc(memo)}</code>\n"
        "(izohsiz to'lovni sizning arizangizga bog'lab bo'lmaydi)\n\n"
        f"💰 Sizga to'lanadi: <b>{fmt_uzs(total)}</b>\n"
        "⏳ Narx 30 daqiqa davomida kafolatlanadi.\n\n"
        "Yuborganingizdan so'ng, to'lov <b>skrinshotini</b> (rasm) shu yerga yuboring 📸"
    )


SELL_NEED_PHOTO = "📸 Iltimos, to'lov skrinshotini rasm ko'rinishida yuboring."
SELL_ASK_CARD = "💳 Pulni sizga yuborishimiz uchun <b>karta raqamingizni</b> kiriting (kamida 16 ta raqam):"
SELL_INVALID_CARD = "❌ Karta raqami noto'g'ri. Kamida 16 ta raqamdan iborat karta raqamini kiriting."


def sell_accepted(order_id: int, currency: str, repriced_total: int | None = None) -> str:
    extra = ""
    if repriced_total is not None:
        extra = (
            f"\nℹ️ Narx kafolati (30 daqiqa) tugagani uchun summa joriy kurs bo'yicha qayta hisoblandi: "
            f"<b>{fmt_uzs(repriced_total)}</b>\n"
        )
    return (
        f"✅ <b>#{order_id}</b> — {currency} sotish arizangiz qabul qilindi!\n{extra}\n"
        "Tez orada adminlar tekshiradi va arizangizni tasdiqlashadi. Natija haqida xabar beramiz."
    )


def sell_approved(order_id: int, total: int) -> str:
    return (
        f"✅ <b>#{order_id}</b> sonli arizangiz tasdiqlandi va siz belgilagan kartaga "
        f"<b>{fmt_uzs(total)}</b> tushurib berildi!"
    )


def sell_cancelled(order_id: int) -> str:
    return (
        f"❌ <b>#{order_id}</b> sonli arizangiz bekor qilindi.\n\n"
        "⚠️ <b>Ogohlantirish:</b> qalbaki ariza yuborish botdan bloklanishga sabab bo'ladi!"
    )


# ---------------- Balans / to'ldirish ----------------
def balance_info(user, orders: dict, ref_count: int, tz: str) -> str:
    from .utils import local_time

    uname = f"@{user.username}" if user.username else "yo'q"
    return (
        f"👤 <b>Profil</b>\n"
        f"├ Ism: <b>{esc(user.first_name)}</b>\n"
        f"├ Username: {esc(uname)}\n"
        f"├ ID: <code>{user.id}</code>\n"
        f"└ Ro'yxatdan o'tgan: {local_time(user.created_at, tz)}\n\n"
        f"💰 <b>Balans: {fmt_uzs(user.balance)}</b>\n\n"
        f"📊 <b>Statistika</b>\n"
        f"├ Jami to'ldirgan: {fmt_uzs(user.total_topup)}\n"
        f"├ Jami sotib olgan: {fmt_uzs(user.total_buy_uzs)}\n"
        f"├ Jami sotgan (yechib olgan): {fmt_uzs(user.total_sell_uzs)}\n"
        f"├ Referaldan ishlagan: {fmt_uzs(user.ref_earned)}\n"
        f"├ Takliflar: {ref_count} ta\n"
        f"└ Arizalar: {orders['total']} ta (bajarilgan: {orders['done']}, kutilmoqda: {orders['waiting']})"
    )


def topup_ask_amount(min_amount: int, max_amount: int) -> str:
    return (
        "💳 <b>Balans to'ldirish</b>\n\n"
        f"📉 Minimal: <b>{fmt_uzs(min_amount)}</b>\n"
        f"📈 Maksimal: <b>{fmt_uzs(max_amount)}</b>\n\n"
        "Balansingizni qancha to'ldirmoqchisiz? Summani so'mda yozing:"
    )


def topup_range(min_amount: int, max_amount: int) -> str:
    return f"❌ Summa <b>{fmt_uzs(min_amount)}</b> dan <b>{fmt_uzs(max_amount)}</b> gacha bo'lishi kerak."


TOPUP_NOT_CONFIGURED = "⚠️ To'lov tizimi hali sozlanmagan (karta raqami yo'q). Adminga murojaat qiling."


def topup_invoice(payment_id: int, amount: int, base_amount: int, card: str, holder: str, minutes: int) -> str:
    extra = ""
    if amount != base_amount:
        extra = (
            f"\n⚠️ Boshqa foydalanuvchi ham <b>{fmt_uzs(base_amount)}</b> to'lamoqda, shuning uchun "
            f"summaga <b>{fmt_uzs(amount - base_amount)}</b> qo'shildi. "
            f"<b>Aynan {fmt_uzs(amount)} yuborishingiz kerak!</b>\n"
        )
    return (
        f"🧾 <b>To'lov cheki #{payment_id}</b>\n\n"
        f"💳 Karta: <code>{esc(card)}</code>\n"
        f"👤 Karta egasi: <b>{esc(holder) or '—'}</b>\n"
        f"💰 Summa: <b>{fmt_uzs(amount)}</b> (aynan shu summani yuboring!)\n"
        f"⏳ Muddat: <b>{minutes} daqiqa</b>\n"
        f"{extra}\n"
        "Pulni yuborganingizdan keyin balansingizga <b>avtomatik</b> tushadi ✅"
    )


def topup_active_exists(amount: int) -> str:
    return (
        f"⏳ Sizda hali tugallanmagan <b>{fmt_uzs(amount)}</b> lik to'lov bor.\n"
        "Avval uni to'lang yoki bekor qiling."
    )


TOPUP_CANCELLED = "❌ To'lov bekor qilindi."
TOPUP_EXPIRED = "⌛️ To'lov muddati tugadi va bekor qilindi. Kerak bo'lsa yangi chek yarating."


def topup_invoice_paid_edit(payment_id: int, amount: int) -> str:
    return f"🧾 To'lov cheki #{payment_id}\n💰 Summa: {fmt_uzs(amount)}\n\n✅ <b>TO'LANDI</b>"


def topup_invoice_expired_edit(payment_id: int, amount: int) -> str:
    return f"🧾 To'lov cheki #{payment_id}\n💰 Summa: {fmt_uzs(amount)}\n\n⌛️ <b>MUDDATI TUGADI</b>"


def topup_invoice_cancelled_edit(payment_id: int, amount: int) -> str:
    return f"🧾 To'lov cheki #{payment_id}\n💰 Summa: {fmt_uzs(amount)}\n\n❌ <b>BEKOR QILINDI</b>"


def topup_paid(amount: int, balance: int) -> str:
    return (
        f"✅ <b>To'lov qabul qilindi!</b>\n\n"
        f"💰 Balansingizga <b>{fmt_uzs(amount)}</b> qo'shildi.\n"
        f"💳 Joriy balans: <b>{fmt_uzs(balance)}</b>"
    )


# ---------------- Kurs & zaxira ----------------
def rates_info(m, tz: str) -> str:
    from .utils import local_time

    if not m.has_rates():
        rates = "⚠️ Kurs hozircha yuklanmadi."
    else:
        rates = (
            f"💎 <b>TonCoin (Gram)</b>\n"
            f"├ Sotib olish: <b>{fmt_uzs(m.buy_price('TON'))}</b>\n"
            f"└ Sotish: <b>{fmt_uzs(m.sell_price('TON'))}</b>\n\n"
            f"💰 <b>USDT (TON)</b>\n"
            f"├ Sotib olish: <b>{fmt_uzs(m.buy_price('USDT'))}</b>\n"
            f"└ Sotish: <b>{fmt_uzs(m.sell_price('USDT'))}</b>\n\n"
            f"🌍 1 USD = {fmt_uzs(int(m.usd_uzs))} | 1 TON = {m.ton_usd:.4f} $"
        )
    updated = local_time(m.reserve_updated_at, tz) if m.reserve_updated_at else "—"
    return (
        f"📊 <b>Kurslar</b>\n{rates}\n\n"
        f"📦 <b>Zaxira (hamyonda)</b>\n"
        f"├ 💎 TON: <b>{fmt_crypto(m.max_buy_units('TON'), 'TON')}</b>\n"
        f"└ 💰 USDT: <b>{fmt_crypto(m.reserve['USDT'], 'USDT')}</b>\n\n"
        f"🕐 Yangilangan: {updated}\n"
        "♻️ Kurs va zaxira har daqiqada avtomatik yangilanadi."
    )


# ---------------- Tarix ----------------
HISTORY_EMPTY = "📃 Sizda hali arizalar yo'q."


def history_page(page: int, pages: int) -> str:
    return f"📃 <b>Almashuv tarixi</b> (sahifa {page + 1}/{pages})\n\nBatafsil ko'rish uchun pastdagi tugmani bosing."


def history_line(order) -> str:
    return f"#{order.id} — {STATUS_TEXT.get(order.status, order.status)}"


HISTORY_ASK_ID = "🔎 Ariza ID raqamini yuboring (masalan: 15):"
HISTORY_NOT_FOUND = "❌ Bunday ariza topilmadi (faqat o'zingizning arizalaringizni ko'ra olasiz)."


def order_details(order, tz: str, link: str | None) -> str:
    from .utils import local_time, mask_card

    lines = [
        f"📄 <b>Ariza #{order.id}</b>",
        f"├ Turi: {TYPE_TEXT.get(order.type, order.type)}",
        f"├ Valyuta: {order.currency}",
        f"├ Miqdor: <b>{fmt_crypto(order.amount_units, order.currency)}</b>",
        f"├ Narx: {fmt_uzs(order.price)} (1 {order.currency})",
        f"├ Jami: <b>{fmt_uzs(order.total_uzs)}</b>",
        f"├ Holati: {STATUS_TEXT.get(order.status, order.status)}",
        f"├ Sana: {local_time(order.created_at, tz)}",
    ]
    if order.type == "buy" and order.wallet_address:
        lines.append(f"├ Hamyon: <code>{esc(order.wallet_address)}</code>")
    if order.type == "sell" and order.card_number:
        lines.append(f"├ Karta: {mask_card(order.card_number)}")
    if order.type == "sell" and getattr(order, "memo", None):
        lines.append(f"├ Izoh (memo): <code>{esc(order.memo)}</code>")
    if link:
        lines.append(f"└ 🔗 <a href=\"{link}\">Tranzaksiya</a>")
    else:
        lines[-1] = lines[-1].replace("├", "└", 1)
    return "\n".join(lines)


# ---------------- Referal ----------------
def referral_info(link: str, percent: float, count: int, earned: int) -> str:
    p = f"{percent:g}"
    return (
        f"🔗 <b>Referal dastur</b>\n\n"
        f"Do'stlaringizni taklif qiling va siz taklif qilgan foydalanuvchi botda qilgan "
        f"<b>har bir ayirboshlashidan {p}% bonus</b> oling!\n\n"
        f"🔗 Sizning havolangiz:\n<code>{esc(link)}</code>\n\n"
        f"👥 Taklif qilganlar: <b>{count} ta</b>\n"
        f"💰 Ishlab topganingiz: <b>{fmt_uzs(earned)}</b>"
    )


def referral_share_text(percent: float) -> str:
    return f"TonCoin (Gram) va USDT ni tez va qulay ayirboshlash boti! Har bir ayirboshlashdan {percent:g}% bonus oling 🎁"


def new_referral(name: str) -> str:
    return f"🎉 Siz yangi referal taklif qildingiz: <b>{esc(name)}</b>!"


def ref_bonus_received(amount: int, name: str) -> str:
    return f"🎁 Referalingiz <b>{esc(name)}</b> ayirboshlash qildi. Sizga bonus: <b>+{fmt_uzs(amount)}</b>"


# ---------------- Qo'llanma ----------------
GUIDE_MENU = "📚 <b>Qo'llanma</b>\n\nMavzuni tanlang:"

GUIDES = {
    "buy_ton": (
        "💎 <b>TonCoin (Gram) sotib olish</b>\n\n"
        "1️⃣ Avval <b>💳 Balans to'ldirish</b> orqali balansingizni so'mda to'ldiring.\n"
        "2️⃣ <b>🔄 Valyuta Ayirboshlash</b> → <b>TonCoin → Sotib olish</b> ni tanlang.\n"
        "3️⃣ Nechta TON olmoqchi ekaningizni yozing (minimal va maksimal ko'rsatiladi).\n"
        "4️⃣ TON hamyon manzilingizni yuboring (UQ… / EQ…).\n"
        "5️⃣ Ma'lumotlarni tekshirib <b>✅ Tasdiqlash</b> ni bosing.\n"
        "6️⃣ Bot bir necha soniya ichida TON ni hamyoningizga <b>avtomatik</b> yuboradi ✅"
    ),
    "sell_ton": (
        "💎 <b>TonCoin (Gram) sotish</b>\n\n"
        "1️⃣ <b>🔄 Valyuta Ayirboshlash</b> → <b>TonCoin → Sotish</b> ni tanlang.\n"
        "2️⃣ Nechta TON sotmoqchi ekaningizni yozing (kurs ko'rsatiladi).\n"
        "3️⃣ Bot bergan hamyon manziliga aynan shu miqdorda TON yuboring — izoh (comment) ga bot bergan kodni yozing 🏷\n"
        "4️⃣ To'lov skrinshotini botga yuboring 📸\n"
        "5️⃣ Pulni qabul qiladigan karta raqamingizni kiriting 💳\n"
        "6️⃣ Admin tekshirib tasdiqlagach, pul kartangizga tushadi ✅"
    ),
    "buy_usdt": (
        "💰 <b>USDT (TON) sotib olish</b>\n\n"
        "1️⃣ <b>💳 Balans to'ldirish</b> orqali balansingizni to'ldiring.\n"
        "2️⃣ <b>🔄 Valyuta Ayirboshlash</b> → <b>USDT → Sotib olish</b> ni tanlang.\n"
        "3️⃣ Miqdorni yozing va TON tarmog'idagi hamyon manzilingizni yuboring.\n"
        "   ⚠️ Faqat <b>TON tarmog'i</b> (TON Space, Tonkeeper, MyTonWallet) — TRC20/ERC20 emas!\n"
        "4️⃣ <b>✅ Tasdiqlash</b> ni bosing — USDT hamyoningizga <b>avtomatik</b> yuboriladi ✅"
    ),
    "sell_usdt": (
        "💰 <b>USDT (TON) sotish</b>\n\n"
        "1️⃣ <b>🔄 Valyuta Ayirboshlash</b> → <b>USDT → Sotish</b> ni tanlang.\n"
        "2️⃣ Miqdorni yozing (kurs ko'rsatiladi).\n"
        "3️⃣ Bot bergan hamyonga aynan shu miqdorda USDT (TON tarmog'i) yuboring — izohga bot bergan kodni yozing 🏷\n"
        "4️⃣ Skrinshot yuboring 📸 va karta raqamingizni kiriting 💳\n"
        "5️⃣ Admin tasdiqlagach, pul kartangizga tushadi ✅"
    ),
}


# ---------------- Qo'llab-quvvatlash ----------------
def support(admin_username: str, news_channel: str, history_channel: str) -> str:
    def link(u: str) -> str:
        u = u.strip()
        if not u:
            return "—"
        if u.startswith("@"):
            return f"@{esc(u[1:])}"
        if u.startswith("-100") or u.lstrip("-").isdigit():
            return "yopiq kanal"
        return f"@{esc(u)}"

    return (
        "☎️ <b>Qo'llab-quvvatlash</b>\n\n"
        f"👤 Admin: {link(admin_username)}\n"
        f"📰 Yangiliklar kanali: {link(news_channel)}\n"
        f"📜 Ayirboshlashlar tarixi kanali: {link(history_channel)}"
    )


# ---------------- Tarix kanali ----------------
def history_channel_post(order, name: str, tz: str) -> str:
    from .utils import local_time

    action = "📥 Sotib oldi" if order.type == "buy" else "📤 Sotdi"
    return (
        "🆕 <b>Yangi ayirboshlash!</b>\n\n"
        f"👤 Mijoz: <b>{esc(name)}</b>\n"
        f"{action}: <b>{fmt_crypto(order.amount_units, order.currency)}</b>\n"
        f"💵 Narx: {fmt_uzs(order.price)}\n"
        f"💰 Summa: <b>{fmt_uzs(order.total_uzs)}</b>\n"
        f"🕐 {local_time(order.created_at, tz)}"
    )

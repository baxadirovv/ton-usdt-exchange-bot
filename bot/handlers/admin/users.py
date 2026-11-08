"""⚙️ User boshqaruv: ID bo'yicha topish, balans qo'shish/ayirish, bloklash."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ... import texts
from ...callbacks import AdmUserCB
from ...config import Config
from ...db import repo
from ...helpers import safe_answer, safe_edit
from ...keyboards.admin import user_manage_kb
from ...keyboards.user import cancel_kb
from ...services.notify import Notifier
from ...states import AdminUserState
from ...utils import esc, fmt_uzs, local_time, parse_int

router = Router(name="admin_users")


async def render_user(user_id: int, cfg: Config) -> tuple[str, bool] | None:
    user = await repo.get_user(user_id)
    if user is None:
        return None
    orders = await repo.user_orders_summary(user.id)
    refs = await repo.count_referrals(user.id)
    uname = f"@{user.username}" if user.username else "—"
    text = (
        f"👤 <b>Foydalanuvchi</b>\n"
        f"├ Ism: <b>{esc(user.first_name)}</b>\n"
        f"├ Username: {esc(uname)}\n"
        f"├ ID: <code>{user.id}</code>\n"
        f"├ Ro'yxatdan o'tgan: {local_time(user.created_at, cfg.timezone)}\n"
        f"├ Oxirgi faollik: {local_time(user.last_seen_at, cfg.timezone)}\n"
        f"├ Taklif qilgan: {refs} ta | Referaldan: {fmt_uzs(user.ref_earned)}\n"
        f"├ Taklif qiluvchi: {user.referrer_id or '—'}\n"
        f"└ Holat: {'🚫 BLOKLANGAN' if user.is_blocked else '✅ faol'}{'' if user.is_active else ' (botni bloklagan)'}\n\n"
        f"💰 Balans: <b>{fmt_uzs(user.balance)}</b>\n"
        f"📥 Jami to'ldirgan: {fmt_uzs(user.total_topup)}\n"
        f"🛒 Jami sotib olgan: {fmt_uzs(user.total_buy_uzs)}\n"
        f"📤 Jami sotgan: {fmt_uzs(user.total_sell_uzs)}\n"
        f"📝 Arizalar: {orders['total']} (bajarilgan {orders['done']}, kutilmoqda {orders['waiting']})"
    )
    return text, user.is_blocked


@router.message(F.text == texts.BTN_A_USERS)
async def a_users(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(AdminUserState.user_id)
    await message.answer("⚙️ Boshqarmoqchi bo'lgan foydalanuvchining <b>Telegram ID</b> raqamini yuboring:", reply_markup=cancel_kb())


@router.message(AdminUserState.user_id, F.text)
async def a_user_lookup(message: Message, state: FSMContext, cfg: Config) -> None:
    raw = (message.text or "").strip()
    if not raw.lstrip("-").isdigit():
        await message.answer("❌ Faqat raqamli Telegram ID yuboring.", reply_markup=cancel_kb())
        return
    rendered = await render_user(int(raw), cfg)
    if rendered is None:
        await message.answer("❌ Bunday foydalanuvchi botda topilmadi.", reply_markup=cancel_kb())
        return
    await state.clear()
    text, blocked = rendered
    await message.answer(text, reply_markup=user_manage_kb(int(raw), blocked))


@router.callback_query(AdmUserCB.filter())
async def cb_user_action(
    call: CallbackQuery,
    callback_data: AdmUserCB,
    state: FSMContext,
    cfg: Config,
    settings,
    notifier: Notifier,
) -> None:
    user_id = callback_data.user_id
    action = callback_data.action

    if action in ("add", "sub"):
        await state.set_state(AdminUserState.amount)
        await state.update_data(user_id=user_id, action=action)
        await safe_answer(call)
        if isinstance(call.message, Message):
            verb = "qo'shiladigan" if action == "add" else "ayiriladigan"
            await call.message.answer(f"💰 Balansga {verb} summani so'mda yuboring:", reply_markup=cancel_kb())
        return

    if action in ("block", "unblock"):
        blocked = action == "block"
        ok = await repo.set_user_blocked(user_id, blocked)
        if not ok:
            await safe_answer(call, "❌ Foydalanuvchi topilmadi", show_alert=True)
            return
        if blocked:
            await notifier.user(user_id, texts.blocked(settings.get("admin_username")))
        else:
            await notifier.user(user_id, "✅ Siz blokdan chiqarildingiz. Botdan foydalanishingiz mumkin.")
        await safe_answer(call, "🚫 Bloklandi" if blocked else "✅ Blokdan chiqarildi")

    rendered = await render_user(user_id, cfg)
    if rendered is None:
        await safe_answer(call, "❌ Foydalanuvchi topilmadi", show_alert=True)
        return
    text, is_blocked = rendered
    await safe_edit(call, text, reply_markup=user_manage_kb(user_id, is_blocked))
    if action == "refresh":
        await safe_answer(call, "🔄 Yangilandi")


@router.message(AdminUserState.amount, F.text)
async def a_user_amount(message: Message, state: FSMContext, cfg: Config, notifier: Notifier) -> None:
    value = parse_int(message.text or "")
    if value is None or value <= 0:
        await message.answer("❌ Musbat butun son kiriting (so'mda).", reply_markup=cancel_kb())
        return
    data = await state.get_data()
    user_id = int(data["user_id"])
    action = data["action"]
    delta = value if action == "add" else -value

    ok = await repo.adjust_balance(user_id, delta)
    await state.clear()
    if not ok:
        await message.answer("❌ Bajarilmadi: foydalanuvchi topilmadi yoki balans yetarli emas.")
        return

    user = await repo.get_user(user_id)
    balance = user.balance if user else 0
    if delta > 0:
        await notifier.user(user_id, f"💰 Balansingizga admin tomonidan <b>{fmt_uzs(value)}</b> qo'shildi.\n💳 Joriy balans: <b>{fmt_uzs(balance)}</b>")
    else:
        await notifier.user(user_id, f"💰 Balansingizdan admin tomonidan <b>{fmt_uzs(value)}</b> ayirildi.\n💳 Joriy balans: <b>{fmt_uzs(balance)}</b>")

    await message.answer("✅ Bajarildi.")
    rendered = await render_user(user_id, cfg)
    if rendered:
        text, is_blocked = rendered
        await message.answer(text, reply_markup=user_manage_kb(user_id, is_blocked))

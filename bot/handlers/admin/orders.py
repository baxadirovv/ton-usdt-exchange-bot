"""Adminning ariza qarorlari: sotish arizasini tasdiqlash/bekor qilish va noaniq arizalarni hal qilish."""
from __future__ import annotations

import html
import time

from aiogram import Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from ... import texts
from ...callbacks import AdmOrderCB, AdmSellCB
from ...config import Config
from ...db import repo
from ...helpers import safe_answer
from ...keyboards.admin import unknown_order_kb
from ...services.exchange import TransferWorker, complete_exchange
from ...services.notify import Notifier
from ...services.settings import SettingsService
from ...services.ton import CONFIRM_MARGIN, TonService
from ...utils import esc, fmt_crypto

router = Router(name="admin_orders")


async def _mark_message(call: CallbackQuery, status_line: str) -> None:
    """Admin xabariga natijani qo'shib, tugmalarni olib tashlaydi."""
    msg = call.message
    if not isinstance(msg, Message):
        return
    who = html.escape(call.from_user.full_name or str(call.from_user.id), quote=False)
    addition = f"\n\n{status_line} — {who}"
    try:
        if msg.photo or msg.document:
            base = msg.html_text if (msg.caption is not None) else ""
            await msg.edit_caption(caption=(base + addition)[:1024], reply_markup=None)
        else:
            await msg.edit_text((msg.html_text + addition)[:4096], reply_markup=None, disable_web_page_preview=True)
    except TelegramAPIError:
        try:
            await msg.edit_reply_markup(reply_markup=None)
        except TelegramAPIError:
            pass


@router.callback_query(AdmSellCB.filter())
async def cb_sell_review(
    call: CallbackQuery,
    callback_data: AdmSellCB,
    cfg: Config,
    settings: SettingsService,
    notifier: Notifier,
) -> None:
    order_id = callback_data.order_id
    if callback_data.action == "ok":
        order = await repo.approve_sell_order(order_id)
        if order is None:
            await safe_answer(call, "Bu ariza allaqachon ko'rib chiqilgan.", show_alert=True)
            await _mark_message(call, "ℹ️ Allaqachon ko'rib chiqilgan")
            return
        await notifier.user(order.user_id, texts.sell_approved(order.id, order.total_uzs))
        await complete_exchange(order, settings, notifier, cfg)
        await _mark_message(call, "✅ TASDIQLANDI")
        await safe_answer(call, "✅ Tasdiqlandi")
        return

    order = await repo.cancel_sell_order(order_id, note="Admin bekor qildi")
    if order is None:
        await safe_answer(call, "Bu ariza allaqachon ko'rib chiqilgan.", show_alert=True)
        await _mark_message(call, "ℹ️ Allaqachon ko'rib chiqilgan")
        return
    await notifier.user(order.user_id, texts.sell_cancelled(order.id))
    await _mark_message(call, "❌ BEKOR QILINDI")
    await safe_answer(call, "❌ Bekor qilindi")


@router.callback_query(AdmOrderCB.filter())
async def cb_unknown_order(
    call: CallbackQuery,
    callback_data: AdmOrderCB,
    cfg: Config,
    settings: SettingsService,
    notifier: Notifier,
    ton: TonService,
    worker: TransferWorker,
) -> None:
    order_id = callback_data.order_id

    if callback_data.action == "recheck":
        order = await repo.start_recheck(order_id)
        if order is None:
            await safe_answer(call, "Bu arizani qayta tekshirib bo'lmaydi (allaqachon hal qilingan yoki xabar ma'lumoti yo'q).", show_alert=True)
            return
        await worker.enqueue_recheck(order)
        await _mark_message(call, "🔄 Qayta tekshirish navbatga qo'yildi")
        await safe_answer(call, "🔄 Tekshirilmoqda — natija alohida xabarda keladi")
        return

    if callback_data.action == "refund":
        current = await repo.get_order(order_id)
        if current is not None and current.msg_valid_until:
            try:
                # blokcheyn vaqti bo'yicha (server soatiga ishonmaymiz)
                wait = int(current.msg_valid_until) + CONFIRM_MARGIN - await ton.chain_time()
            except Exception:  # noqa: BLE001 — TON Center ishlamasa, katta zaxira bilan mahalliy vaqt
                wait = int(current.msg_valid_until) + 300 - int(time.time())
            if wait > 0:
                # xabar hali tarmoqqa kirishi mumkin — pulni qaytarish xavfli
                await safe_answer(
                    call,
                    f"⏳ Yuborilgan xabar muddati hali tugamagan. {wait} soniyadan keyin qayta urinib ko'ring "
                    "(yoki 🔄 Qayta tekshirish ni bosing).",
                    show_alert=True,
                )
                return

    if callback_data.action == "done":
        order = await repo.resolve_unknown_order(order_id, success=True, note="Admin: yuborilgan deb tasdiqladi")
        if order is None:
            await safe_answer(call, "Bu ariza allaqachon hal qilingan.", show_alert=True)
            await _mark_message(call, "ℹ️ Allaqachon hal qilingan")
            return
        link = ton.explorer_link(order.tx_hash) if order.tx_hash else ton.address_link(order.wallet_address or "")
        await notifier.user(order.user_id, texts.buy_done(order.id, order.amount_units, order.currency, link))
        await complete_exchange(order, settings, notifier, cfg)
        await _mark_message(call, "✅ YUBORILGAN deb belgilandi")
        await safe_answer(call, "✅ Bajarildi")
        return

    order = await repo.resolve_unknown_order(order_id, success=False, note="Admin: yuborilmagan, pul qaytarildi")
    if order is None:
        await safe_answer(call, "Bu ariza allaqachon hal qilingan.", show_alert=True)
        await _mark_message(call, "ℹ️ Allaqachon hal qilingan")
        return
    await notifier.user(order.user_id, texts.buy_resolved_refund(order.id, order.total_uzs))
    await _mark_message(call, "↩️ PUL QAYTARILDI")
    await safe_answer(call, "↩️ Balans qaytarildi")


@router.message(Command("unknown"))
async def list_unknown(message: Message) -> None:
    """Noaniq arizalar ro'yxati (yordamchi buyruq)."""
    orders = await repo.list_unknown_orders(20)
    if not orders:
        await message.answer("✅ Noaniq arizalar yo'q.")
        return
    for o in orders[:20]:
        await message.answer(
            f"❓ <b>#{o.id}</b> | 👤 <code>{o.user_id}</code> | {fmt_crypto(o.amount_units, o.currency)}\n"
            f"📍 <code>{esc(o.wallet_address)}</code>\n"
            f"Izoh: {esc(o.note or '—')}",
            reply_markup=unknown_order_kb(o.id, can_recheck=bool(o.msg_hash)),
        )

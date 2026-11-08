"""
Balans to'ldirish (avto to'lov):
  - noyob summa yaratish (bir xil summada 2 ta faol chek bo'lmaydi; band bo'lsa +1..50 so'm qo'shiladi)
  - /pay ga kelgan so'rovni cheklar bilan solishtirish va balansga qo'shish
  - muddati (standart 5 daqiqa) o'tgan cheklarni avtomatik bekor qilish
"""
from __future__ import annotations

import asyncio
import logging
import secrets
from decimal import Decimal, InvalidOperation

from .. import texts
from ..config import Config
from ..db import repo
from ..db.models import Payment
from ..utils import fmt_uzs
from .notify import Notifier
from .settings import SettingsService

log = logging.getLogger("payments")

UNIQUE_WINDOW_MINUTES = 90   # shu vaqt ichida yaratilgan cheklar summasi takrorlanmaydi (kechikkan/takroriy SMS boshqa odamga tushmasin)
LATE_WINDOW_MINUTES = 45     # muddati o'tgan chekka kechikib kelgan to'lov shu vaqt ichida qabul qilinadi
EXTRA_MIN, EXTRA_MAX = 1, 50


def parse_webhook_amount(raw: object) -> int | None:
    """'541545.00' / '541 545' / '541545,00' / '541,545.00' -> 541545 (so'm)."""
    if raw is None:
        return None
    cleaned = str(raw).strip().replace(" ", "").replace(" ", "").replace("'", "")
    if not cleaned:
        return None
    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(",", "")          # 541,545.00
    elif cleaned.count(",") == 1:
        cleaned = cleaned.replace(",", ".")         # 541545,00
    else:
        cleaned = cleaned.replace(",", "")
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return None
    if not value.is_finite() or value <= 0:
        return None
    return int(value.to_integral_value())


class PaymentService:
    def __init__(self, cfg: Config, settings: SettingsService, notifier: Notifier) -> None:
        self.cfg = cfg
        self.settings = settings
        self.notifier = notifier
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    async def create_unique(self, user_id: int, base_amount: int) -> Payment:
        """Takrorlanmaydigan summa bilan chek yaratadi."""
        async with self._lock:
            taken = await repo.reserved_payment_amounts(UNIQUE_WINDOW_MINUTES)
            amount = base_amount
            if amount in taken:
                free = [base_amount + i for i in range(EXTRA_MIN, EXTRA_MAX + 1) if base_amount + i not in taken]
                if not free:
                    free = [base_amount + i for i in range(EXTRA_MAX + 1, EXTRA_MAX + 1000) if base_amount + i not in taken]
                amount = free[secrets.randbelow(min(len(free), EXTRA_MAX))] if free else base_amount + EXTRA_MAX + 1000
            return await repo.create_payment(user_id, amount, base_amount, self.cfg.payment_timeout_minutes)

    # ------------------------------------------------------------------
    async def process_incoming(self, raw_amount: object, method: str | None) -> tuple[str, Payment | None]:
        """/pay dan kelgan so'rov. ('matched' | 'not_found' | 'bad_amount', payment)"""
        amount = parse_webhook_amount(raw_amount)
        if amount is None:
            return "bad_amount", None

        payment = await repo.match_and_pay(amount, method, LATE_WINDOW_MINUTES)
        await repo.log_incoming_payment(amount, str(raw_amount), method, payment.id if payment else None)

        if payment is None:
            log.warning("Mos chek topilmadi: %s so'm (%s)", amount, method)
            await self.notifier.admins(
                f"⚠️ <b>Mos kelmaydigan to'lov keldi</b>\n"
                f"💰 Summa: <b>{fmt_uzs(amount)}</b>\n"
                f"📲 Manba: {method or '—'}\n"
                "Bu summada chek topilmadi. Kerak bo'lsa foydalanuvchiga qo'lda qo'shing (⚙️ User boshqaruv)."
            )
            return "not_found", None

        user = await repo.get_user(payment.user_id)
        balance = user.balance if user else payment.amount
        await self.notifier.edit_user_message(
            payment.user_id, payment.message_id, texts.topup_invoice_paid_edit(payment.id, payment.amount)
        )
        await self.notifier.user(payment.user_id, texts.topup_paid(payment.amount, balance))
        await self.notifier.admins(
            f"✅ <b>To'lov qabul qilindi</b> (chek #{payment.id})\n"
            f"👤 <code>{payment.user_id}</code>\n"
            f"💰 {fmt_uzs(payment.amount)} | 📲 {method or '—'}"
        )
        return "matched", payment

    # ------------------------------------------------------------------
    async def expire_once(self) -> list[Payment]:
        expired = await repo.expire_payments()
        for p in expired:
            await self.notifier.edit_user_message(p.user_id, p.message_id, texts.topup_invoice_expired_edit(p.id, p.amount))
            await self.notifier.user(p.user_id, texts.TOPUP_EXPIRED)
        return expired

    async def process_inbox_once(self) -> int:
        """Hosting (public/pay.php) yozgan to'lov xabarlarini qayta ishlaydi."""
        items = await repo.claim_inbox(limit=50)
        for item in items:
            result, payment_id = "error", None
            try:
                result, payment = await self.process_incoming(item.raw_amount, item.method)
                payment_id = payment.id if payment else None
            except Exception as e:  # noqa: BLE001
                log.exception("Inbox #%s ni qayta ishlashda xato: %s", item.id, e)
            await repo.finish_inbox(item.id, result, payment_id)
        return len(items)

    async def run_loop(self) -> None:
        reset = await repo.reset_stuck_inbox()
        if reset:
            log.warning("%s ta to'lov xabari qayta ishlash uchun navbatga qaytarildi", reset)
        tick = 0
        while True:
            try:
                await self.process_inbox_once()
            except Exception as e:  # noqa: BLE001
                log.exception("To'lov navbatini o'qishda xato: %s", e)
            if tick % 5 == 0:
                try:
                    await self.expire_once()
                except Exception as e:  # noqa: BLE001
                    log.exception("To'lov muddati tekshiruvida xato: %s", e)
            tick += 1
            await asyncio.sleep(2)

    def start(self) -> None:
        self._task = asyncio.create_task(self.run_loop(), name="payments-loop")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

"""
Ayirboshlash yakunlanganda bajariladigan umumiy ishlar:
referal bonusi, foyda hisobi, tarix kanaliga post.
Hamda sotib olish arizalarini navbat bilan blokcheynga yuboruvchi worker.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from ton_core import Address

from .. import texts
from ..config import Config
from ..db import repo
from ..db.models import ORDER_BUY, ST_PROCESSING, ST_SENDING, Order
from ..keyboards.admin import unknown_order_kb
from ..utils import esc, fmt_crypto, fmt_uzs, from_units
from .market import MarketService
from .notify import Notifier
from .settings import SettingsService
from .ton import SendResult, SignedMessage, TonService

log = logging.getLogger("exchange")


async def complete_exchange(order: Order, settings: SettingsService, notifier: Notifier, cfg: Config) -> None:
    """Ariza muvaffaqiyatli yakunlangach: referal bonusi, foyda, tarix kanali."""
    try:
        user = await repo.get_user(order.user_id)
        if user is None:
            return

        # ---- referal bonusi (ayirboshlash summasidan foiz) ----
        bonus = 0
        percent = settings.ref_percent
        if user.referrer_id and percent > 0:
            bonus = int((Decimal(order.total_uzs) * Decimal(str(percent)) / Decimal(100)).to_integral_value(rounding=ROUND_HALF_UP))
            if bonus > 0 and await repo.add_ref_bonus(user.referrer_id, user.id, order.id, bonus, percent):
                await repo.set_order_ref_bonus(order.id, bonus)
                await notifier.user(user.referrer_id, texts.ref_bonus_received(bonus, user.first_name))
            else:
                bonus = 0

        # ---- foyda ----
        if order.type == ORDER_BUY:
            amount = from_units(order.amount_units, order.currency)
            markup_profit = int((amount * Decimal(order.price - order.market_price)).to_integral_value(rounding=ROUND_HALF_UP))
            await repo.add_profit(order.id, markup_profit - bonus, f"ustama {markup_profit}, referal -{bonus}")
        else:
            await repo.add_profit(order.id, -bonus, f"mijozdan sotib olish, referal -{bonus}")

        # ---- tarix kanali (faqat ism) ----
        await notifier.history_channel(texts.history_channel_post(order, user.first_name, cfg.timezone))
    except Exception as e:  # noqa: BLE001
        log.exception("complete_exchange xatosi (#%s): %s", order.id, e)


@dataclass
class Job:
    kind: str        # send | recheck
    order_id: int
    currency: str
    units: int


class TransferWorker:
    """Sotib olish arizalarini navbat bilan yuboradi (bir vaqtda bittadan)."""

    def __init__(
        self,
        cfg: Config,
        settings: SettingsService,
        ton: TonService,
        market: MarketService,
        notifier: Notifier,
    ) -> None:
        self.cfg = cfg
        self.settings = settings
        self.ton = ton
        self.market = market
        self.notifier = notifier
        self.queue: asyncio.Queue[Job] = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self._busy = asyncio.Event()
        self._busy.set()  # set = hozir hech narsa bajarilmayapti
        self._stopping = False

    # ------------------------------------------------------------------
    def start(self) -> None:
        self._stopping = False
        self._task = asyncio.create_task(self._run(), name="transfer-worker")
        self._task.add_done_callback(self._on_task_done)

    def _on_task_done(self, task: asyncio.Task) -> None:
        if self._stopping or task.cancelled():
            return
        log.error("Transfer worker kutilmaganda to'xtadi (%s) — qayta ishga tushirilmoqda", task.exception())
        self.start()

    async def stop(self, timeout: float = 60.0) -> None:
        """Joriy yuborishni tugatishga imkon beradi (timeout gacha), keyin to'xtaydi."""
        self._stopping = True
        if self._task is None:
            return
        try:
            await asyncio.wait_for(self._busy.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            log.warning("Joriy transfer %s soniyada tugamadi — qayta ishga tushganda avtomatik tekshiriladi", timeout)
        self._task.cancel()
        try:
            await self._task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass

    async def enqueue(self, order: Order) -> None:
        """Yangi arizani navbatga qo'yadi va miqdorni zaxiradan band qiladi."""
        self.market.hold(order.currency, order.amount_units)
        await self.queue.put(Job("send", order.id, order.currency, order.amount_units))

    async def enqueue_recheck(self, order: Order) -> None:
        """Avval yuborilgan xabar natijasini qayta tekshirish."""
        self.market.hold(order.currency, order.amount_units)
        await self.queue.put(Job("recheck", order.id, order.currency, order.amount_units))

    # ------------------------------------------------------------------
    async def _run(self) -> None:
        while True:
            job = await self.queue.get()
            if self._stopping:
                # to'xtatilmoqda — yangi ishni boshlamaymiz (ariza bazada qoladi, qayta ishga tushganda davom etadi)
                self.market.release(job.currency, job.units)
                self.queue.task_done()
                continue
            self._busy.clear()
            try:
                if job.kind == "recheck":
                    await self.recheck(job.order_id)
                else:
                    await self.process(job.order_id)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                log.exception("Transfer worker xatosi (#%s): %s", job.order_id, e)
                await self._safe_mark_unknown(job.order_id, f"Kutilmagan xato: {e}")
            finally:
                self.market.release(job.currency, job.units)
                self._busy.set()
                self.queue.task_done()

    async def _safe_mark_unknown(self, order_id: int, reason: str) -> None:
        try:
            order = await repo.mark_order_unknown(order_id, reason[:300])
            if order is not None:
                await self._notify_unknown(order, reason)
        except Exception as e:  # noqa: BLE001
            log.exception("Arizani 'noaniq' deb belgilab bo'lmadi (#%s): %s", order_id, e)

    async def process(self, order_id: int) -> None:
        order = await repo.get_order(order_id)
        if order is None or order.status != ST_PROCESSING:
            return
        try:
            destination = Address(order.wallet_address or "")
        except Exception as e:  # noqa: BLE001 — hech narsa yuborilmagan
            await self._fail(order, SendResult("failed", reason=f"manzil noto'g'ri: {e}"))
            return

        # processing -> sending
        order = await repo.start_sending(order_id)
        if order is None:
            return

        async def on_signed(msg: SignedMessage) -> None:
            await repo.save_order_message(order_id, msg.norm_hash, msg.raw_hash, msg.seqno, msg.valid_until)

        comment = f"Order #{order.id}"
        if order.currency == "TON":
            result = await self.ton.send_ton(destination, order.amount_units, comment, on_signed=on_signed)
        else:
            result = await self.ton.send_usdt(destination, order.amount_units, comment, query_id=order.id, on_signed=on_signed)
        await self._handle_result(order, result)

    async def recheck(self, order_id: int) -> None:
        order = await repo.get_order(order_id)
        if order is None or order.status != ST_SENDING:
            return
        if not order.msg_hash or order.msg_seqno is None or order.msg_valid_until is None:
            await self._safe_mark_unknown(order_id, "xabar ma'lumoti saqlanmagan")
            return
        msg = SignedMessage(
            norm_hash=order.msg_hash,
            raw_hash=order.msg_raw_hash or "",
            seqno=int(order.msg_seqno),
            valid_until=int(order.msg_valid_until),
            kind="ton" if order.currency == "TON" else "usdt",
        )
        result = await self.ton.confirm(msg)
        await self._handle_result(order, result)

    async def _handle_result(self, order: Order, result: SendResult) -> None:
        if result.status == "done":
            await self._done(order, result)
        elif result.status == "failed":
            await self._fail(order, result)
        else:
            unknown = await repo.mark_order_unknown(order.id, result.reason or "noaniq", result.tx_hash or None)
            if unknown is not None:
                await self._notify_unknown(unknown, result.reason)

    async def _done(self, order: Order, result: SendResult) -> None:
        done = await repo.finish_buy_order(order.id, result.tx_hash, result.reason or None)
        if done is None:
            return
        link = self.ton.explorer_link(result.tx_hash) if result.tx_hash else self.ton.address_link(done.wallet_address or "")
        await self.notifier.user(done.user_id, texts.buy_done(done.id, done.amount_units, done.currency, link))
        await complete_exchange(done, self.settings, self.notifier, self.cfg)
        await self.notifier.admins(
            f"✅ <b>#{done.id}</b> sotib olish bajarildi\n"
            f"👤 <code>{done.user_id}</code>\n"
            f"💱 {fmt_crypto(done.amount_units, done.currency)} → {fmt_uzs(done.total_uzs)}\n"
            f"📍 <code>{esc(done.wallet_address)}</code>\n"
            f"🔗 {link}"
        )
        try:
            await self.market.refresh_reserve()
        except Exception:  # noqa: BLE001
            pass

    async def _fail(self, order: Order, result: SendResult) -> None:
        failed = await repo.fail_buy_order(order.id, result.reason or "bajarilmadi", result.tx_hash or None)
        if failed is None:
            return
        await self.notifier.user(order.user_id, texts.buy_failed(order.id))
        await self.notifier.admins(
            f"❌ <b>#{order.id}</b> sotib olish bajarilmadi, pul balansga qaytarildi.\n"
            f"👤 <code>{order.user_id}</code> | {fmt_crypto(order.amount_units, order.currency)}\n"
            f"Sabab: <code>{esc((result.reason or '')[:300])}</code>"
        )

    async def _notify_unknown(self, order: Order, reason: str) -> None:
        await self.notifier.user(order.user_id, texts.buy_checking(order.id))
        link = self.ton.explorer_link(order.tx_hash) if order.tx_hash else self.ton.address_link(self.ton.address)
        await self.notifier.admins(
            f"❓ <b>#{order.id}</b> — tranzaksiya natijasi noaniq.\n"
            f"👤 <code>{order.user_id}</code> | {fmt_crypto(order.amount_units, order.currency)}\n"
            f"📍 Mijoz hamyoni: <code>{esc(order.wallet_address)}</code>\n"
            f"Sabab: <code>{esc((reason or '')[:300])}</code>\n"
            f"🔗 {link}\n\n"
            "Avval 🔄 Qayta tekshirish ni bosing. Natija baribir noaniq bo'lsa, Tonviewer'da tekshirib qaror qiling:",
            reply_markup=unknown_order_kb(order.id, can_recheck=bool(order.msg_hash)),
        )


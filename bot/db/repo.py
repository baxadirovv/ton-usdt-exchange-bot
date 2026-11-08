"""
Baza bilan ishlash funksiyalari (CRUD).

Har bir funksiya o'z sessiyasini ochadi va yopadi. Holat o'zgarishlari (ariza tasdiqlash,
to'lovni qabul qilish va h.k.) ATOMAR shartli UPDATE orqali bajariladi — bir xil amal
ikki marta bajarilib qolmaydi (masalan, ikki admin bir vaqtda "Tasdiqlash" bossa ham).
"""
from __future__ import annotations

import asyncio
import functools
import inspect
import logging
import random
import time
from datetime import timedelta
from typing import Any, Iterable, Sequence

from sqlalchemy import case, delete, func, select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    CANCELLED,
    FINISHED_OK,
    ORDER_BUY,
    ORDER_SELL,
    PAY_CANCELLED,
    PAY_EXPIRED,
    PAY_PAID,
    PAY_PENDING,
    ST_APPROVED,
    ST_CANCELLED,
    ST_DONE,
    ST_FAILED,
    ST_PENDING,
    ST_PROCESSING,
    ST_SENDING,
    ST_UNKNOWN,
    WAITING,
    INBOX_DONE,
    INBOX_NEW,
    INBOX_PROCESSING,
    Channel,
    IncomingPayment,
    Order,
    PayInbox,
    Payment,
    Profit,
    RefBonus,
    Setting,
    StockAlert,
    User,
    utcnow,
)
from .session import session_scope

log = logging.getLogger("repo")


# =====================================================================
#  USERS
# =====================================================================
async def get_or_create_user(
    user_id: int,
    first_name: str,
    username: str | None,
    referrer_id: int | None = None,
) -> tuple[User, bool]:
    """Foydalanuvchini topadi yoki yaratadi. (user, yangi_yaratildimi) qaytaradi."""
    first_name = (first_name or "")[:128]
    for _ in range(2):
        try:
            async with session_scope() as s:
                user = await s.get(User, user_id)
                if user is None:
                    if referrer_id is not None and (referrer_id == user_id or await s.get(User, referrer_id) is None):
                        referrer_id = None
                    user = User(id=user_id, first_name=first_name, username=username, referrer_id=referrer_id)
                    s.add(user)
                    await s.flush()
                    return user, True

                user.last_seen_at = utcnow()
                if user.first_name != first_name:
                    user.first_name = first_name
                if user.username != username:
                    user.username = username
                if not user.is_active:
                    user.is_active = True
                return user, False
        except IntegrityError:
            # bir vaqtda ikki so'rov kelib, ikkinchisi ham yaratmoqchi bo'ldi — qayta o'qiymiz
            continue
    user = await get_user(user_id)
    assert user is not None
    return user, False


MAX_DB_INT = 2**62


async def get_user(user_id: int) -> User | None:
    if not -MAX_DB_INT < int(user_id) < MAX_DB_INT:
        return None
    async with session_scope() as s:
        return await s.get(User, user_id)


async def set_user_blocked(user_id: int, blocked: bool) -> bool:
    if not -MAX_DB_INT < int(user_id) < MAX_DB_INT:
        return False
    async with session_scope() as s:
        res = await s.execute(update(User).where(User.id == user_id).values(is_blocked=blocked))
        return res.rowcount > 0


async def set_user_active(user_id: int, active: bool) -> None:
    async with session_scope() as s:
        await s.execute(update(User).where(User.id == user_id, User.is_active.is_not(active)).values(is_active=active))


async def adjust_balance(user_id: int, delta: int) -> bool:
    """Balansni o'zgartiradi. Manfiy delta uchun balans yetarli bo'lmasa False."""
    if not -MAX_DB_INT < int(user_id) < MAX_DB_INT or abs(int(delta)) >= 10**15:
        return False
    async with session_scope() as s:
        stmt = update(User).where(User.id == user_id)
        if delta < 0:
            stmt = stmt.where(User.balance >= -delta)
        res = await s.execute(stmt.values(balance=User.balance + delta))
        return res.rowcount > 0


async def mark_ref_credited(user_id: int) -> bool:
    """Referal birinchi marta tasdiqlansa True (faqat bir marta)."""
    async with session_scope() as s:
        res = await s.execute(
            update(User).where(User.id == user_id, User.ref_credited.is_(False)).values(ref_credited=True)
        )
        return res.rowcount == 1


async def users_stats() -> dict[str, Any]:
    async with session_scope() as s:
        total = (await s.execute(select(func.count(User.id)))).scalar_one()
        blocked = (await s.execute(select(func.count(User.id)).where(User.is_blocked.is_(True)))).scalar_one()
        balances = (await s.execute(select(func.coalesce(func.sum(User.balance), 0)))).scalar_one()
        today = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        today_new = (await s.execute(select(func.count(User.id)).where(User.created_at >= today))).scalar_one()
        inactive = (await s.execute(select(func.count(User.id)).where(User.is_active.is_(False)))).scalar_one()
        return {
            "total": int(total),
            "blocked": int(blocked),
            "balances": int(balances or 0),
            "today_new": int(today_new),
            "inactive": int(inactive),
        }


async def all_broadcast_user_ids() -> list[int]:
    async with session_scope() as s:
        rows = await s.execute(
            select(User.id).where(User.is_active.is_(True), User.is_blocked.is_(False)).order_by(User.id)
        )
        return [int(r[0]) for r in rows.all()]


async def count_referrals(user_id: int) -> int:
    """Tasdiqlangan (obuna shartidan o'tgan) takliflar soni."""
    async with session_scope() as s:
        return int((await s.execute(
            select(func.count(User.id)).where(User.referrer_id == user_id, User.ref_credited.is_(True))
        )).scalar_one())


async def top_referrers(limit: int = 10) -> list[tuple[User, int]]:
    """(user, taklif_soni) — ishlagan summasi bo'yicha kamayish tartibida."""
    async with session_scope() as s:
        sub = (
            select(User.referrer_id.label("rid"), func.count(User.id).label("cnt"))
            .where(User.referrer_id.is_not(None), User.ref_credited.is_(True))
            .group_by(User.referrer_id)
            .subquery()
        )
        cnt = func.coalesce(sub.c.cnt, 0)
        rows = await s.execute(
            select(User, cnt)
            .outerjoin(sub, sub.c.rid == User.id)
            .where((User.ref_earned > 0) | (cnt > 0))
            .order_by(User.ref_earned.desc(), cnt.desc())
            .limit(limit)
        )
        return [(u, int(c)) for u, c in rows.all()]


# =====================================================================
#  ORDERS
# =====================================================================
async def _transition(
    s: AsyncSession,
    order_id: int,
    from_statuses: Iterable[str],
    to_status: str,
    **values: Any,
) -> Order | None:
    """Arizani faqat kutilgan holatdan yangi holatga o'tkazadi (atomar). Muvaffaqiyatsa Order."""
    if not 0 < int(order_id) < 2**31:
        return None
    res = await s.execute(
        update(Order)
        .where(Order.id == order_id, Order.status.in_(list(from_statuses)))
        .values(status=to_status, updated_at=utcnow(), **values)
        .execution_options(synchronize_session=False)
    )
    if res.rowcount != 1:
        return None
    return await s.get(Order, order_id)


async def create_buy_order_and_charge(
    user_id: int,
    currency: str,
    amount_units: int,
    price: int,
    market_price: int,
    total_uzs: int,
    wallet_address: str,
) -> Order | None:
    """Balansdan summani yechadi va 'processing' ariza yaratadi (bitta tranzaksiyada).
    Balans yetarli bo'lmasa (yoki bloklangan bo'lsa) None."""
    async with session_scope() as s:
        res = await s.execute(
            update(User)
            .where(User.id == user_id, User.balance >= total_uzs, User.is_blocked.is_(False))
            .values(balance=User.balance - total_uzs)
        )
        if res.rowcount == 0:
            return None
        order = Order(
            user_id=user_id,
            type=ORDER_BUY,
            currency=currency,
            amount_units=amount_units,
            price=price,
            market_price=market_price,
            total_uzs=total_uzs,
            status=ST_PROCESSING,
            wallet_address=wallet_address,
        )
        s.add(order)
        await s.flush()
        return order


async def create_sell_order(
    user_id: int,
    currency: str,
    amount_units: int,
    price: int,
    total_uzs: int,
    wallet_address: str,
    screenshot_file_id: str,
    card_number: str,
    memo: str | None = None,
    note: str | None = None,
) -> Order:
    async with session_scope() as s:
        order = Order(
            user_id=user_id,
            memo=memo,
            note=note,
            type=ORDER_SELL,
            currency=currency,
            amount_units=amount_units,
            price=price,
            market_price=price,
            total_uzs=total_uzs,
            status=ST_PENDING,
            wallet_address=wallet_address,
            screenshot_file_id=screenshot_file_id,
            card_number=card_number,
        )
        s.add(order)
        await s.flush()
        return order


async def get_order(order_id: int) -> Order | None:
    if not 0 < int(order_id) < 2**31:
        return None
    async with session_scope() as s:
        return await s.get(Order, order_id)


async def get_user_order(user_id: int, order_id: int) -> Order | None:
    if not 0 < int(order_id) < 2**31:
        return None
    async with session_scope() as s:
        order = await s.get(Order, order_id)
        if order is None or order.user_id != user_id:
            return None
        return order


async def list_user_orders(user_id: int, page: int, per_page: int = 6) -> tuple[list[Order], int]:
    page = max(0, min(int(page), 1_000_000))
    async with session_scope() as s:
        total = int((await s.execute(select(func.count(Order.id)).where(Order.user_id == user_id))).scalar_one())
        rows = await s.execute(
            select(Order)
            .where(Order.user_id == user_id)
            .order_by(Order.id.desc())
            .offset(max(0, page) * per_page)
            .limit(per_page)
        )
        return list(rows.scalars().all()), total


async def start_sending(order_id: int) -> Order | None:
    """Navbatdagi arizani 'yuborilmoqda' holatiga o'tkazadi (processing -> sending)."""
    async with session_scope() as s:
        return await _transition(s, order_id, [ST_PROCESSING], ST_SENDING, send_started_at=int(time.time()))


async def finish_buy_order(order_id: int, tx_hash: str, note: str | None = None) -> Order | None:
    """Sotib olish arizasi muvaffaqiyatli yakunlandi (sending -> done)."""
    async with session_scope() as s:
        order = await _transition(s, order_id, [ST_SENDING, ST_PROCESSING], ST_DONE, tx_hash=tx_hash, note=note)
        if order is None:
            return None
        await s.execute(
            update(User).where(User.id == order.user_id).values(total_buy_uzs=User.total_buy_uzs + order.total_uzs)
        )
        return order


async def fail_buy_order(order_id: int, note: str, tx_hash: str | None = None) -> Order | None:
    """Sotib olish arizasi bajarilmadi (processing/sending -> failed) va pul balansga qaytariladi."""
    async with session_scope() as s:
        values: dict[str, Any] = {"note": note[:500]}
        if tx_hash:
            values["tx_hash"] = tx_hash
        order = await _transition(s, order_id, [ST_PROCESSING, ST_SENDING], ST_FAILED, **values)
        if order is None:
            return None
        await s.execute(update(User).where(User.id == order.user_id).values(balance=User.balance + order.total_uzs))
        return order


async def mark_order_unknown(order_id: int, note: str, tx_hash: str | None = None) -> Order | None:
    """Natija noaniq (processing/sending -> unknown) — admin qaror qiladi."""
    async with session_scope() as s:
        values: dict[str, Any] = {"note": note[:500]}
        if tx_hash:
            values["tx_hash"] = tx_hash
        return await _transition(s, order_id, [ST_PROCESSING, ST_SENDING], ST_UNKNOWN, **values)


async def recover_orders_on_startup() -> tuple[list[Order], list[Order]]:
    """Bot qayta ishga tushganda:
    - 'processing' (hali yuborish boshlanmagan) arizalar -> qayta navbatga;
    - 'sending' va xabar ma'lumoti saqlanmagan (imzolanmagan/yuborilmagan) -> 'processing', qayta navbatga;
    - 'sending' va xabar ma'lumoti saqlangan -> natija avtomatik qayta tekshiriladi.
    Natija: (qayta_navbatga, qayta_tekshirishga)"""
    async with session_scope() as s:
        # Shu versiya: xabar saqlanmagan bo'lsa — yuborilmagani kafolatlangan -> qayta navbatga
        unsigned = (await s.execute(
            select(Order.id).where(
                Order.status == ST_SENDING, Order.msg_hash.is_(None), Order.send_started_at.is_not(None)
            )
        )).all()
        for (oid,) in unsigned:
            await _transition(s, int(oid), [ST_SENDING], ST_PROCESSING)
        # Eski versiyadan qolgan (belgisiz) yuborilayotgan arizalar — xavfsiz tomonga: admin tekshiradi
        legacy = (await s.execute(
            select(Order.id).where(
                Order.status == ST_SENDING, Order.msg_hash.is_(None), Order.send_started_at.is_(None)
            )
        )).all()
        for (oid,) in legacy:
            await _transition(s, int(oid), [ST_SENDING], ST_UNKNOWN, note="Eski versiyadan qolgan: yuborilgan-yuborilmaganini tekshiring")
        queued = list((await s.execute(
            select(Order).where(Order.status == ST_PROCESSING).order_by(Order.id)
        )).scalars().all())
        recheck = list((await s.execute(
            select(Order).where(Order.status == ST_SENDING, Order.msg_hash.is_not(None)).order_by(Order.id)
        )).scalars().all())
        return queued, recheck


async def save_order_message(order_id: int, norm_hash: str, raw_hash: str, seqno: int, valid_until: int) -> bool:
    """Imzolangan xabar ma'lumotini YUBORISHDAN OLDIN saqlaydi."""
    async with session_scope() as s:
        res = await s.execute(
            update(Order)
            .where(Order.id == order_id, Order.status == ST_SENDING)
            .values(msg_hash=norm_hash, msg_raw_hash=raw_hash, msg_seqno=seqno, msg_valid_until=valid_until, tx_hash=norm_hash)
            .execution_options(synchronize_session=False)
        )
        if res.rowcount != 1:
            raise RuntimeError(f"#{order_id} ariza 'sending' holatida emas")
        return True


async def start_recheck(order_id: int) -> Order | None:
    """Noaniq arizani qayta tekshirish uchun 'sending' holatiga qaytaradi (faqat xabar ma'lumoti bo'lsa)."""
    async with session_scope() as s:
        res = await s.execute(
            update(Order)
            .where(Order.id == order_id, Order.status == ST_UNKNOWN, Order.msg_hash.is_not(None))
            .values(status=ST_SENDING, updated_at=utcnow())
            .execution_options(synchronize_session=False)
        )
        if res.rowcount != 1:
            return None
        return await s.get(Order, order_id)


async def list_unknown_orders(limit: int = 50) -> list[Order]:
    async with session_scope() as s:
        rows = await s.execute(select(Order).where(Order.status == ST_UNKNOWN).order_by(Order.id).limit(limit))
        return list(rows.scalars().all())


async def resolve_unknown_order(order_id: int, success: bool, note: str) -> Order | None:
    """Holati noma'lum arizani admin qarori bilan yakunlash."""
    async with session_scope() as s:
        if success:
            order = await _transition(s, order_id, [ST_UNKNOWN], ST_DONE, note=note)
            if order is not None:
                await s.execute(
                    update(User).where(User.id == order.user_id).values(total_buy_uzs=User.total_buy_uzs + order.total_uzs)
                )
        else:
            order = await _transition(s, order_id, [ST_UNKNOWN], ST_FAILED, note=note)
            if order is not None:
                await s.execute(update(User).where(User.id == order.user_id).values(balance=User.balance + order.total_uzs))
        return order


async def approve_sell_order(order_id: int) -> Order | None:
    async with session_scope() as s:
        order = await _transition(s, order_id, [ST_PENDING], ST_APPROVED)
        if order is None:
            return None
        await s.execute(
            update(User).where(User.id == order.user_id).values(total_sell_uzs=User.total_sell_uzs + order.total_uzs)
        )
        return order


async def cancel_sell_order(order_id: int, note: str | None = None) -> Order | None:
    async with session_scope() as s:
        return await _transition(s, order_id, [ST_PENDING], ST_CANCELLED, note=note)


async def set_order_ref_bonus(order_id: int, bonus: int) -> None:
    async with session_scope() as s:
        await s.execute(update(Order).where(Order.id == order_id).values(ref_bonus=bonus))


async def orders_stats() -> dict[str, Any]:
    async with session_scope() as s:
        total = int((await s.execute(select(func.count(Order.id)))).scalar_one())
        done = int((await s.execute(select(func.count(Order.id)).where(Order.status.in_(FINISHED_OK)))).scalar_one())
        waiting = int((await s.execute(select(func.count(Order.id)).where(Order.status.in_(WAITING)))).scalar_one())
        cancelled = int((await s.execute(select(func.count(Order.id)).where(Order.status.in_(CANCELLED)))).scalar_one())

        async def _sum(column, order_type: str, status: str, currency: str | None = None) -> int:
            stmt = select(func.coalesce(func.sum(column), 0)).where(Order.type == order_type, Order.status == status)
            if currency is not None:
                stmt = stmt.where(Order.currency == currency)
            return int((await s.execute(stmt)).scalar_one())

        return {
            "total": total,
            "done": done,
            "waiting": waiting,
            "cancelled": cancelled,
            "sold_ton": await _sum(Order.amount_units, ORDER_BUY, ST_DONE, "TON"),
            "sold_usdt": await _sum(Order.amount_units, ORDER_BUY, ST_DONE, "USDT"),
            "sold_uzs": await _sum(Order.total_uzs, ORDER_BUY, ST_DONE),
            "bought_ton": await _sum(Order.amount_units, ORDER_SELL, ST_APPROVED, "TON"),
            "bought_usdt": await _sum(Order.amount_units, ORDER_SELL, ST_APPROVED, "USDT"),
            "bought_uzs": await _sum(Order.total_uzs, ORDER_SELL, ST_APPROVED),
        }


async def user_orders_summary(user_id: int) -> dict[str, int]:
    async with session_scope() as s:
        rows = await s.execute(
            select(
                func.count(Order.id),
                func.coalesce(func.sum(case((Order.status.in_(FINISHED_OK), 1), else_=0)), 0),
                func.coalesce(func.sum(case((Order.status.in_(WAITING), 1), else_=0)), 0),
            ).where(Order.user_id == user_id)
        )
        total, done, waiting = rows.one()
        return {"total": int(total), "done": int(done or 0), "waiting": int(waiting or 0)}


# =====================================================================
#  PAYMENTS (balans to'ldirish)
# =====================================================================
async def get_active_payment(user_id: int) -> Payment | None:
    async with session_scope() as s:
        rows = await s.execute(
            select(Payment)
            .where(Payment.user_id == user_id, Payment.status == PAY_PENDING, Payment.expires_at > utcnow())
            .order_by(Payment.id.desc())
        )
        return rows.scalars().first()


async def reserved_payment_amounts(window_minutes: int) -> set[int]:
    """Yangi chek uchun ishlatib bo'lmaydigan summalar: barcha faol cheklar +
    oxirgi `window_minutes` daqiqada yaratilgan har qanday chek (kech kelgan yoki takroriy
    to'lov xabari boshqa odamga tushib qolmasligi uchun)."""
    since = utcnow() - timedelta(minutes=window_minutes)
    async with session_scope() as s:
        rows = await s.execute(
            select(Payment.amount).where((Payment.status == PAY_PENDING) | (Payment.created_at >= since))
        )
        return {int(r[0]) for r in rows.all()}


async def create_payment(user_id: int, amount: int, base_amount: int, timeout_minutes: int) -> Payment:
    async with session_scope() as s:
        p = Payment(
            user_id=user_id,
            amount=amount,
            base_amount=base_amount,
            status=PAY_PENDING,
            expires_at=utcnow() + timedelta(minutes=timeout_minutes),
        )
        s.add(p)
        await s.flush()
        return p


async def set_payment_message(payment_id: int, message_id: int) -> None:
    async with session_scope() as s:
        await s.execute(update(Payment).where(Payment.id == payment_id).values(message_id=message_id))


async def _pay_transition(
    s: AsyncSession,
    payment_id: int,
    to_status: str,
    from_statuses: Iterable[str] = (PAY_PENDING,),
    **values: Any,
) -> Payment | None:
    if not 0 < int(payment_id) < 2**31:
        return None
    res = await s.execute(
        update(Payment)
        .where(Payment.id == payment_id, Payment.status.in_(list(from_statuses)))
        .values(status=to_status, **values)
        .execution_options(synchronize_session=False)
    )
    if res.rowcount != 1:
        return None
    return await s.get(Payment, payment_id)


async def cancel_payment(payment_id: int, user_id: int | None = None) -> Payment | None:
    if not 0 < int(payment_id) < 2**31:
        return None
    async with session_scope() as s:
        if user_id is not None:
            owner = (await s.execute(select(Payment.user_id).where(Payment.id == payment_id))).scalar_one_or_none()
            if owner != user_id:
                return None
        return await _pay_transition(s, payment_id, PAY_CANCELLED)


async def expire_payments() -> list[Payment]:
    """Muddati o'tgan cheklarni 'expired' qiladi va ro'yxatini qaytaradi."""
    async with session_scope() as s:
        rows = await s.execute(
            select(Payment.id).where(Payment.status == PAY_PENDING, Payment.expires_at <= utcnow())
        )
        result: list[Payment] = []
        for (pid,) in rows.all():
            p = await _pay_transition(s, int(pid), PAY_EXPIRED)
            if p is not None:
                result.append(p)
        return result


async def match_and_pay(amount: int, method: str | None, late_window_minutes: int = 30) -> Payment | None:
    """Kelgan summa bo'yicha chekni topib, to'langan deb belgilaydi va balansga qo'shadi.

    1) Avval faol (pending) cheklar orasidan qidiriladi.
    2) Topilmasa — oxirgi `late_window_minutes` daqiqada muddati o'tgan yoki bekor qilingan
       chek (foydalanuvchi kechikib to'lagan bo'lsa ham puli yo'qolmaydi).
    To'langan chek qayta mos kelmaydi — takroriy xabar ikki marta pul qo'shmaydi."""
    since = utcnow() - timedelta(minutes=late_window_minutes)
    paid_values = {"paid_at": utcnow(), "method": (method or "")[:64] or None}
    async with session_scope() as s:
        searches = (
            ((PAY_PENDING,), select(Payment.id).where(Payment.status == PAY_PENDING, Payment.amount == amount).order_by(Payment.id.asc())),
            (
                (PAY_EXPIRED, PAY_CANCELLED),
                select(Payment.id)
                .where(
                    Payment.status.in_([PAY_EXPIRED, PAY_CANCELLED]),
                    Payment.amount == amount,
                    Payment.created_at >= since,
                )
                .order_by(Payment.id.desc()),
            ),
        )
        for from_statuses, stmt in searches:
            rows = await s.execute(stmt.limit(5))
            for (pid,) in rows.all():
                p = await _pay_transition(s, int(pid), PAY_PAID, from_statuses, **paid_values)
                if p is None:
                    continue
                await s.execute(
                    update(User)
                    .where(User.id == p.user_id)
                    .values(balance=User.balance + p.amount, total_topup=User.total_topup + p.amount)
                )
                return p
        return None


async def log_incoming_payment(amount: int, raw_amount: str, method: str | None, payment_id: int | None) -> None:
    async with session_scope() as s:
        s.add(
            IncomingPayment(
                amount=amount,
                raw_amount=str(raw_amount)[:32],
                method=(method or "")[:64] or None,
                payment_id=payment_id,
                matched=payment_id is not None,
            )
        )


# =====================================================================
#  PROFITS
# =====================================================================
async def add_profit(order_id: int, amount_uzs: int, note: str | None = None) -> None:
    async with session_scope() as s:
        s.add(Profit(order_id=order_id, amount_uzs=amount_uzs, note=(note or "")[:128] or None))


async def profit_stats() -> dict[str, int]:
    async with session_scope() as s:
        total = int((await s.execute(select(func.coalesce(func.sum(Profit.amount_uzs), 0)))).scalar_one())
        today = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        today_sum = int((await s.execute(
            select(func.coalesce(func.sum(Profit.amount_uzs), 0)).where(Profit.created_at >= today)
        )).scalar_one())
        return {"total": total, "today": today_sum}


# =====================================================================
#  SETTINGS
# =====================================================================
async def load_all_settings() -> dict[str, str]:
    async with session_scope() as s:
        rows = await s.execute(select(Setting))
        return {r.key: r.value for r in rows.scalars().all()}


async def save_setting(key: str, value: str) -> None:
    async with session_scope() as s:
        row = await s.get(Setting, key)
        if row is None:
            s.add(Setting(key=key, value=value))
        else:
            row.value = value


# =====================================================================
#  CHANNELS
# =====================================================================
async def list_channels() -> list[Channel]:
    async with session_scope() as s:
        rows = await s.execute(select(Channel).order_by(Channel.id))
        return list(rows.scalars().all())


async def get_channel(channel_id: int) -> Channel | None:
    if not 0 < int(channel_id) < 2**31:
        return None
    async with session_scope() as s:
        return await s.get(Channel, channel_id)


async def add_channel(chat_id: int, username: str, title: str) -> Channel:
    async with session_scope() as s:
        rows = await s.execute(select(Channel).where(Channel.chat_id == chat_id))
        ch = rows.scalars().first()
        if ch is None:
            ch = Channel(chat_id=chat_id, username=username, title=title[:128])
            s.add(ch)
        else:
            ch.username = username
            ch.title = title[:128]
        await s.flush()
        return ch


async def update_channel(channel_id: int, chat_id: int, username: str, title: str) -> Channel | None:
    if not 0 < int(channel_id) < 2**31:
        return None
    async with session_scope() as s:
        ch = await s.get(Channel, channel_id)
        if ch is None:
            return None
        other = (await s.execute(
            select(Channel.id).where(Channel.chat_id == chat_id, Channel.id != channel_id)
        )).scalar_one_or_none()
        if other is not None:
            await s.execute(delete(Channel).where(Channel.id == other))
        ch.chat_id = chat_id
        ch.username = username
        ch.title = title[:128]
        await s.flush()
        return ch


async def delete_channel(channel_id: int) -> bool:
    if not 0 < int(channel_id) < 2**31:
        return False
    async with session_scope() as s:
        res = await s.execute(delete(Channel).where(Channel.id == channel_id))
        return res.rowcount > 0


# =====================================================================
#  STOCK ALERTS
# =====================================================================
async def add_stock_alert(user_id: int, currency: str) -> bool:
    """True — yangi qo'shildi, False — allaqachon bor edi."""
    try:
        async with session_scope() as s:
            exists = (await s.execute(
                select(StockAlert.id).where(StockAlert.user_id == user_id, StockAlert.currency == currency)
            )).first()
            if exists is not None:
                return False
            s.add(StockAlert(user_id=user_id, currency=currency))
            await s.flush()
            return True
    except IntegrityError:
        return False


async def pop_stock_alerts(currency: str) -> list[int]:
    """Kutayotganlar ro'yxatini qaytaradi va jadvaldan o'chiradi (bir martalik)."""
    async with session_scope() as s:
        rows = await s.execute(
            select(StockAlert.id, StockAlert.user_id).where(StockAlert.currency == currency).with_for_update()
        )
        items = rows.all()
        if not items:
            return []
        await s.execute(delete(StockAlert).where(StockAlert.id.in_([int(r[0]) for r in items])))
        return [int(r[1]) for r in items]


# =====================================================================
#  REFERRAL
# =====================================================================
async def add_ref_bonus(referrer_id: int, referred_id: int, order_id: int, amount_uzs: int, percent: float) -> bool:
    """Taklif qiluvchiga bonus beradi (balans + ref_earned). Topilmasa/bloklangan bo'lsa False."""
    if amount_uzs <= 0:
        return False
    async with session_scope() as s:
        res = await s.execute(
            update(User)
            .where(User.id == referrer_id, User.is_blocked.is_(False))
            .values(balance=User.balance + amount_uzs, ref_earned=User.ref_earned + amount_uzs)
        )
        if res.rowcount != 1:
            return False
        s.add(RefBonus(referrer_id=referrer_id, referred_id=referred_id, order_id=order_id, amount_uzs=amount_uzs, percent=percent))
        return True


async def ref_bonus_total() -> int:
    async with session_scope() as s:
        return int((await s.execute(select(func.coalesce(func.sum(RefBonus.amount_uzs), 0)))).scalar_one())


# =====================================================================
#  Yordamchi
# =====================================================================
async def users_by_ids(ids: Sequence[int]) -> list[User]:
    if not ids:
        return []
    async with session_scope() as s:
        rows = await s.execute(select(User).where(User.id.in_(list(ids))))
        return list(rows.scalars().all())


# =====================================================================
#  PAY INBOX (hostingdagi public/pay.php yozadi)
# =====================================================================
async def claim_inbox(limit: int = 20) -> list[PayInbox]:
    """Yangi xabarlarni 'processing' holatiga o'tkazib oladi (atomar, faqat bir marta)."""
    claimed: list[PayInbox] = []
    async with session_scope() as s:
        rows = await s.execute(
            select(PayInbox.id).where(PayInbox.status == INBOX_NEW).order_by(PayInbox.id).limit(limit)
        )
        for (iid,) in rows.all():
            res = await s.execute(
                update(PayInbox)
                .where(PayInbox.id == iid, PayInbox.status == INBOX_NEW)
                .values(status=INBOX_PROCESSING)
                .execution_options(synchronize_session=False)
            )
            if res.rowcount == 1:
                item = await s.get(PayInbox, iid)
                if item is not None:
                    claimed.append(item)
    return claimed


async def finish_inbox(inbox_id: int, result: str, payment_id: int | None) -> None:
    async with session_scope() as s:
        await s.execute(
            update(PayInbox)
            .where(PayInbox.id == inbox_id)
            .values(status=INBOX_DONE, result=result[:32], payment_id=payment_id, processed_at=utcnow())
        )


async def reset_stuck_inbox() -> int:
    """Bot to'xtab qolganda 'processing' da qolgan xabarlar qayta ishlanadi
    (to'langan chek qayta mos kelmaydi — ikki marta qo'shilmaydi)."""
    async with session_scope() as s:
        res = await s.execute(
            update(PayInbox).where(PayInbox.status == INBOX_PROCESSING).values(status=INBOX_NEW)
        )
        return int(res.rowcount or 0)


async def add_inbox(raw_amount: str, method: str | None, remote_ip: str | None = None) -> int:
    """(Testlar va qo'lda kiritish uchun) — odatda bu ishni public/pay.php bajaradi."""
    async with session_scope() as s:
        item = PayInbox(raw_amount=str(raw_amount)[:64], method=(method or "")[:64] or None, remote_ip=remote_ip, status=INBOX_NEW)
        s.add(item)
        await s.flush()
        return int(item.id)


# =====================================================================
#  MySQL: deadlock / lock-wait bo'lsa avtomatik qayta urinish
# =====================================================================
_RETRYABLE_MYSQL_CODES = {1205, 1213}  # lock wait timeout, deadlock — tranzaksiya to'liq bekor qilinadi


def _is_retryable(exc: OperationalError) -> bool:
    args = getattr(getattr(exc, "orig", None), "args", ())
    return bool(args) and args[0] in _RETRYABLE_MYSQL_CODES


def _db_retry(fn):
    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        for attempt in range(5):
            try:
                return await fn(*args, **kwargs)
            except OperationalError as e:
                if attempt == 4 or not _is_retryable(e):
                    raise
                log.warning("MySQL qulf to'qnashuvi (%s), qayta urinish %s: %s", fn.__name__, attempt + 1, e.orig)
                await asyncio.sleep(0.05 * (attempt + 1) + random.random() * 0.05)
    return wrapper


def _wrap_public_functions() -> None:
    namespace = globals()
    for name, obj in list(namespace.items()):
        # avval isfunction: Python 3.12.0–3.12.x da inspect.iscoroutinefunction(<inspect moduli>) xato True qaytaradi
        if name.startswith("_") or not inspect.isfunction(obj):
            continue
        if getattr(obj, "__module__", None) == __name__ and inspect.iscoroutinefunction(obj):
            namespace[name] = _db_retry(obj)


_wrap_public_functions()

"""
Ma'lumotlar bazasi jadvallari (SQLAlchemy 2.0, async).

Pul birliklari:
  - so'm (UZS)  -> butun son (Integer)
  - TON         -> nanoton (1 TON = 10^9)  -> BigInteger `amount_units`
  - USDT        -> mikro-USDT (1 USDT = 10^6) -> BigInteger `amount_units`
Shunday qilib hech qanday float xatoligi bo'lmaydi.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    """Naive UTC vaqt (bazada shu ko'rinishda saqlanadi)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


# MySQL: InnoDB (tranzaksiyalar, qatorli qulflar) va utf8mb4 (emoji va o'zbekcha harflar uchun)
MYSQL_TABLE_ARGS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_unicode_ci",
}


# ---- Ariza (order) turlari va holatlari ----
ORDER_BUY = "buy"
ORDER_SELL = "sell"

# buy:  processing (navbatda) -> sending (yuborilmoqda) -> done | failed | unknown
# sell: pending -> approved | cancelled
ST_PROCESSING = "processing"
ST_SENDING = "sending"
ST_DONE = "done"
ST_FAILED = "failed"
ST_UNKNOWN = "unknown"
ST_PENDING = "pending"
ST_APPROVED = "approved"
ST_CANCELLED = "cancelled"

FINISHED_OK = (ST_DONE, ST_APPROVED)
WAITING = (ST_PROCESSING, ST_SENDING, ST_PENDING, ST_UNKNOWN)
CANCELLED = (ST_FAILED, ST_CANCELLED)

# ---- To'lov (balans to'ldirish) holatlari ----
PAY_PENDING = "pending"
PAY_PAID = "paid"
PAY_CANCELLED = "cancelled"
PAY_EXPIRED = "expired"

CURRENCIES = ("TON", "USDT")


class User(Base):
    __tablename__ = "users"
    __table_args__ = MYSQL_TABLE_ARGS

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)  # Telegram ID
    first_name: Mapped[str] = mapped_column(String(128), default="")
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)

    balance: Mapped[int] = mapped_column(BigInteger, default=0)          # so'm
    total_topup: Mapped[int] = mapped_column(BigInteger, default=0)      # jami to'ldirgan (so'm)
    total_buy_uzs: Mapped[int] = mapped_column(BigInteger, default=0)    # jami sotib olgan (so'm)
    total_sell_uzs: Mapped[int] = mapped_column(BigInteger, default=0)   # jami sotgan (so'm, tasdiqlangan)
    ref_earned: Mapped[int] = mapped_column(BigInteger, default=0)       # referaldan ishlagan (so'm)

    referrer_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    ref_credited: Mapped[bool] = mapped_column(Boolean, default=False)   # taklif qiluvchiga xabar berildimi

    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)     # admin bloklagan
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)       # botni o'zi bloklamagan

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = MYSQL_TABLE_ARGS

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    type: Mapped[str] = mapped_column(String(8))            # buy | sell
    currency: Mapped[str] = mapped_column(String(8))        # TON | USDT
    amount_units: Mapped[int] = mapped_column(BigInteger)   # nanoton / mikro-USDT
    price: Mapped[int] = mapped_column(BigInteger)          # 1 dona narxi (so'm) — mijoz uchun
    market_price: Mapped[int] = mapped_column(BigInteger, default=0)  # o'sha paytdagi real kurs (so'm)
    total_uzs: Mapped[int] = mapped_column(BigInteger)      # jami summa (so'm)
    status: Mapped[str] = mapped_column(String(16), index=True)

    wallet_address: Mapped[str | None] = mapped_column(String(80), nullable=True)   # buy: mijoz hamyoni; sell: bizning hamyon
    card_number: Mapped[str | None] = mapped_column(String(32), nullable=True)      # sell: mijoz kartasi
    screenshot_file_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    tx_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    ref_bonus: Mapped[int] = mapped_column(BigInteger, default=0)

    # sotib olish: yuborishdan OLDIN saqlanadigan imzolangan xabar ma'lumotlari (qayta tekshirish uchun)
    msg_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    msg_raw_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    msg_seqno: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    msg_valid_until: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # yuborish shu versiyada boshlangan (xabar ma'lumoti saqlanmagan bo'lsa — hech narsa yuborilmagani kafolatlangan)
    send_started_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # sotish: mijoz o'tkazmasiga yozadigan izoh (memo) — qaysi to'lov qaysi arizaga tegishli ekanini aniqlash uchun
    memo: Mapped[str | None] = mapped_column(String(32), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Payment(Base):
    """Balans to'ldirish cheki (avto to'lov)."""
    __tablename__ = "payments"
    __table_args__ = MYSQL_TABLE_ARGS

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    amount: Mapped[int] = mapped_column(BigInteger)         # aynan yuborilishi kerak bo'lgan summa (so'm)
    base_amount: Mapped[int] = mapped_column(BigInteger)    # foydalanuvchi so'ragan summa
    status: Mapped[str] = mapped_column(String(16), index=True)
    message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # chek xabari (tahrirlash uchun)
    method: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class IncomingPayment(Base):
    """/pay ga kelgan har bir so'rov logi (mos kelgan yoki kelmagan)."""
    __tablename__ = "incoming_payments"
    __table_args__ = MYSQL_TABLE_ARGS

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    amount: Mapped[int] = mapped_column(BigInteger)
    raw_amount: Mapped[str] = mapped_column(String(32), default="")
    method: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payment_id: Mapped[int | None] = mapped_column(Integer, nullable=True)   # mos kelgan chek
    matched: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Profit(Base):
    """Har bir ayirboshlashdan foyda (so'm, manfiy bo'lishi ham mumkin)."""
    __tablename__ = "profits"
    __table_args__ = MYSQL_TABLE_ARGS

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(Integer, ForeignKey("orders.id"), index=True)
    amount_uzs: Mapped[int] = mapped_column(BigInteger)
    note: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Setting(Base):
    __tablename__ = "settings"
    __table_args__ = MYSQL_TABLE_ARGS

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


class Channel(Base):
    """Majburiy obuna kanallari."""
    __tablename__ = "channels"
    __table_args__ = MYSQL_TABLE_ARGS

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    username: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class StockAlert(Base):
    """Zaxira tugaganda 'kelganda xabar ber' deganlar (bir martalik)."""
    __tablename__ = "stock_alerts"
    __table_args__ = (UniqueConstraint("user_id", "currency", name="uq_stock_alert"), MYSQL_TABLE_ARGS)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    currency: Mapped[str] = mapped_column(String(8))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class RefBonus(Base):
    """Referal bonuslari logi."""
    __tablename__ = "ref_bonuses"
    __table_args__ = MYSQL_TABLE_ARGS

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    referrer_id: Mapped[int] = mapped_column(BigInteger, index=True)
    referred_id: Mapped[int] = mapped_column(BigInteger)
    order_id: Mapped[int] = mapped_column(Integer)
    amount_uzs: Mapped[int] = mapped_column(BigInteger)
    percent: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ---- Hosting (PHP) orqali kelgan to'lov xabarlari navbati ----
INBOX_NEW = "new"
INBOX_PROCESSING = "processing"
INBOX_DONE = "done"


class PayInbox(Base):
    """public/pay.php yozadigan navbat: bot har 2 soniyada o'qib, cheklarga moslaydi."""
    __tablename__ = "pay_inbox"
    __table_args__ = MYSQL_TABLE_ARGS

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    raw_amount: Mapped[str] = mapped_column(String(64))
    method: Mapped[str | None] = mapped_column(String(64), nullable=True)
    remote_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), index=True, default=INBOX_NEW)
    result: Mapped[str | None] = mapped_column(String(32), nullable=True)
    payment_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


Index("ix_orders_user_created", Order.user_id, Order.created_at)
Index("ix_payments_status_amount", Payment.status, Payment.amount)

"""Umumiy yordamchi funksiyalar: pul formatlash, miqdor parse qilish, HTML escape."""
from __future__ import annotations

import html
import re
from datetime import datetime, timedelta, timezone
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal, InvalidOperation

DECIMALS = {"TON": 9, "USDT": 6}
SYMBOL = {"TON": "💎", "USDT": "💰"}
NAME = {"TON": "TonCoin (Gram)", "USDT": "USDT (TON)"}
SHORT = {"TON": "TON", "USDT": "USDT"}
MAX_INPUT_DECIMALS = 6  # foydalanuvchi kiritadigan maksimal kasr xonalar


def esc(text: object) -> str:
    """HTML uchun xavfsiz matn."""
    return html.escape(str(text if text is not None else ""), quote=False)


def to_units(amount: Decimal, currency: str) -> int:
    """1.5 TON -> 1500000000 (nanoton)."""
    return int((amount * (Decimal(10) ** DECIMALS[currency])).to_integral_value(rounding=ROUND_DOWN))


def from_units(units: int, currency: str) -> Decimal:
    return Decimal(units) / (Decimal(10) ** DECIMALS[currency])


def fmt_amount(units: int, currency: str, max_decimals: int = 6) -> str:
    """1500000000, TON -> '1.5'"""
    d = from_units(units, currency).quantize(Decimal(1) / (Decimal(10) ** max_decimals), rounding=ROUND_DOWN)
    text = format(d.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def fmt_crypto(units: int, currency: str) -> str:
    return f"{fmt_amount(units, currency)} {SHORT[currency]}"


def fmt_uzs(value: int | float | Decimal, suffix: str = " so'm") -> str:
    """27000 -> '27 000 so'm'"""
    n = int(Decimal(value).to_integral_value(rounding=ROUND_HALF_UP))
    sign = "-" if n < 0 else ""
    return f"{sign}{abs(n):,}".replace(",", " ") + suffix


def fmt_dec(value: Decimal | float, max_decimals: int = 4) -> str:
    d = Decimal(value).quantize(Decimal(1) / (Decimal(10) ** max_decimals), rounding=ROUND_DOWN)
    text = format(d.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def parse_decimal(text: str) -> Decimal | None:
    """'1,5' / ' 1.5 ' / '2' -> Decimal; noto'g'ri bo'lsa None."""
    if not text:
        return None
    cleaned = text.strip().replace(",", ".").replace(" ", "")
    if not re.fullmatch(r"\d+(\.\d+)?", cleaned):
        return None
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return None
    if value <= 0:
        return None
    # juda ko'p kasr xonalarni kesamiz
    return value.quantize(Decimal(1) / (Decimal(10) ** MAX_INPUT_DECIMALS), rounding=ROUND_DOWN)


def parse_int(text: str) -> int | None:
    """'10 000' / '10000' / '10000.00' -> 10000"""
    if not text:
        return None
    cleaned = text.strip().replace(" ", "").replace(" ", "").replace(",", ".")
    if not re.fullmatch(r"\d+(\.\d+)?", cleaned):
        return None
    try:
        return int(Decimal(cleaned).to_integral_value(rounding=ROUND_HALF_UP))
    except InvalidOperation:
        return None


def parse_signed_int(text: str) -> int | None:
    """'-5000' / '+5000' / '5000'"""
    if not text:
        return None
    cleaned = text.strip().replace(" ", "")
    sign = 1
    if cleaned.startswith("-"):
        sign = -1
        cleaned = cleaned[1:]
    elif cleaned.startswith("+"):
        cleaned = cleaned[1:]
    value = parse_int(cleaned)
    return None if value is None else sign * value


def calc_total(amount: Decimal, price: int) -> int:
    """miqdor × narx -> so'm (yaxlitlangan)."""
    return int((amount * Decimal(price)).to_integral_value(rounding=ROUND_HALF_UP))


def only_digits(text: str) -> str:
    return re.sub(r"\D", "", text or "")


def mask_card(card: str) -> str:
    d = only_digits(card)
    if len(d) < 8:
        return d
    return f"{d[:4]} **** **** {d[-4:]}"


def fmt_card(card: str) -> str:
    d = only_digits(card)
    return " ".join(d[i:i + 4] for i in range(0, len(d), 4)) if d else card


def local_time(dt: datetime, tz_name: str = "Asia/Tashkent") -> str:
    """Naive UTC -> mahalliy vaqt matni."""
    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(tz_name)
    except Exception:  # pragma: no cover
        tz = timezone(timedelta(hours=5))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz).strftime("%d.%m.%Y %H:%M")


def now_local_str(tz_name: str = "Asia/Tashkent") -> str:
    return local_time(datetime.now(timezone.utc), tz_name)


def chunks(items: list, size: int) -> list[list]:
    return [items[i:i + size] for i in range(0, len(items), size)]

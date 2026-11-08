"""
Admin paneldan o'zgartiriladigan sozlamalar.
Hammasi `settings` jadvalida saqlanadi va xotirada keshlanadi.
"""
from __future__ import annotations

import secrets
from decimal import Decimal

from ..db import repo

DEFAULTS: dict[str, str] = {
    # Qo'shimcha sozlamalar
    "admin_username": "",
    "news_channel": "",         # @username
    "history_channel": "",      # @username yoki -100... (bot admin bo'lishi shart)
    "buy_enabled": "1",
    "sell_wallet_address": "",  # bo'sh bo'lsa — hot wallet manzili
    # Narxlar & miqdor
    "markup_uzs": "1000",       # ustama (so'm) — TON va USDT uchun
    "buy_min_ton": "0.1",
    "buy_min_usdt": "1",
    "sell_min_ton": "0.1",
    "sell_max_ton": "100",
    "sell_min_usdt": "1",
    "sell_max_usdt": "1000",
    # To'lov tizimi
    "card_number": "",
    "card_holder": "",
    "pay_secret_key": "",
    "topup_min": "10000",
    "topup_max": "10000000",
    # Referal
    "ref_percent": "2",
    # Avtomatik yangilanadigan qiymatlar (oxirgi ma'lum qiymat)
    "rate_ton_usd": "0",
    "rate_usdt_usd": "1",
    "rate_usd_uzs": "0",
    "rates_updated_at": "",
    "rates_source": "",
    "reserve_ton": "0",
    "reserve_usdt": "0",
    "reserve_updated_at": "",
}


class SettingsService:
    def __init__(self) -> None:
        self._cache: dict[str, str] = dict(DEFAULTS)

    async def load(self) -> None:
        stored = await repo.load_all_settings()
        self._cache = {**DEFAULTS, **stored}
        if not self._cache.get("pay_secret_key"):
            await self.set("pay_secret_key", secrets.token_hex(16))

    # ---- o'qish ----
    def get(self, key: str, default: str = "") -> str:
        return self._cache.get(key, DEFAULTS.get(key, default))

    def get_int(self, key: str, default: int = 0) -> int:
        try:
            return int(Decimal(self.get(key)))
        except Exception:
            return default

    def get_float(self, key: str, default: float = 0.0) -> float:
        try:
            return float(self.get(key))
        except Exception:
            return default

    def get_decimal(self, key: str, default: str = "0") -> Decimal:
        try:
            return Decimal(self.get(key))
        except Exception:
            return Decimal(default)

    def get_bool(self, key: str) -> bool:
        return self.get(key).strip().lower() in ("1", "true", "yes", "on", "ha")

    # ---- yozish ----
    async def set(self, key: str, value: str | int | float | Decimal | bool) -> None:
        if isinstance(value, bool):
            value = "1" if value else "0"
        text = str(value)
        self._cache[key] = text
        await repo.save_setting(key, text)

    async def regenerate_secret(self) -> str:
        key = secrets.token_hex(16)
        await self.set("pay_secret_key", key)
        return key

    # ---- qulay xususiyatlar ----
    @property
    def buy_enabled(self) -> bool:
        return self.get_bool("buy_enabled")

    @property
    def markup(self) -> int:
        return max(0, self.get_int("markup_uzs"))

    @property
    def ref_percent(self) -> float:
        return max(0.0, self.get_float("ref_percent"))

    def buy_min(self, currency: str) -> Decimal:
        return self.get_decimal(f"buy_min_{currency.lower()}", "0.1")

    def sell_min(self, currency: str) -> Decimal:
        return self.get_decimal(f"sell_min_{currency.lower()}", "0.1")

    def sell_max(self, currency: str) -> Decimal:
        return self.get_decimal(f"sell_max_{currency.lower()}", "100")

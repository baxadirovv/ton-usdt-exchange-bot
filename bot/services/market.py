"""
Kurs (TON/USDT -> so'm) va hot wallet zaxirasini har 1 daqiqada yangilab turish.

Kurs manbalari (hammasi bepul, API kalitsiz) — bir vaqtda so'raladi, MEDIANA olinadi:
  TON/USD : CoinGecko (the-open-network), Binance (GRAMUSDT), KuCoin (GRAM-USDT)
  USDT/USD: CoinGecko (tether), bo'lmasa 1.0
  USD/UZS : O'zbekiston Markaziy banki (cbu.uz) -> open.er-api.com -> currency-api (jsDelivr / pages.dev)
            (30 daqiqa keshlanadi)

Binance: avval rasmiy "faqat bozor ma'lumotlari" manzili data-api.binance.vision so'raladi —
api.binance.com ba'zi mamlakat/server IP manzillariga HTTP 451 (Unavailable For Legal Reasons) qaytaradi.
CBU: chet eldagi serverga javob bermasligi mumkin — shunda 1 soat davomida zaxira manbalar ishlatiladi
(har yangilanishda timeout kutib o'tirilmaydi).
Ishlamayotgan manba logga birinchi marta va keyin har 6 soatda bir yoziladi (har daqiqada emas).

Himoyalar:
  - manbalar orasida 10% dan ko'p farq qilgan narx tashlab yuboriladi;
  - bir yangilanishda TON kursi 25% dan, dollar kursi 10% dan ko'p o'zgarsa — qabul qilinmaydi,
    adminga xabar boradi (admin "Kurs va zaxirani hozir yangilash" tugmasi bilan majburan yangilashi mumkin);
  - kurs 10 daqiqadan eski bo'lsa — sotib olish/sotish vaqtincha to'xtaydi ("kurs mavjud emas").
"""
from __future__ import annotations

import asyncio
import logging
import statistics
import time
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Awaitable, Callable
from urllib.parse import urlsplit

import aiohttp

from ..config import Config
from ..utils import to_units
from .settings import SettingsService
from .ton import MIN_GAS_RESERVE_NANO, TonService

log = logging.getLogger("market")

HTTP_TIMEOUT = aiohttp.ClientTimeout(total=8)
CBU_TIMEOUT = aiohttp.ClientTimeout(total=6)
HEADERS = {"User-Agent": "ton-exchange-bot/1.0", "Accept": "application/json"}

COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price?ids={ids}&vs_currencies=usd"
BINANCE_URLS = (
    "https://data-api.binance.vision/api/v3/ticker/price?symbol=GRAMUSDT",  # rasmiy, faqat ochiq bozor ma'lumotlari
    "https://api.binance.com/api/v3/ticker/price?symbol=GRAMUSDT",
)
KUCOIN_URL = "https://api.kucoin.com/api/v1/market/orderbook/level1?symbol=GRAM-USDT"
CBU_URL = "https://cbu.uz/uz/arkhiv-kursov-valyut/json/USD/"
ERAPI_URL = "https://open.er-api.com/v6/latest/USD"
CURRENCY_API_URLS = (
    "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/usd.json",
    "https://latest.currency-api.pages.dev/v1/currencies/usd.json",
)

COINGECKO_TON_ID = "the-open-network"
COINGECKO_USDT_ID = "tether"

CBU_RETRY_AFTER = 3600                   # CBU javob bermasa — shuncha soniya zaxira manbalardan foydalaniladi
SOURCE_LOG_REPEAT = 6 * 3600             # ishlamayotgan manba haqidagi ogohlantirish takrorlanish oralig'i
USD_UZS_RANGE = (1_000.0, 200_000.0)     # bundan tashqari qiymat — xato javob deb hisoblanadi
USD_UZS_CACHE_SECONDS = 30 * 60
RATE_MAX_AGE = timedelta(minutes=10)     # bundan eski kurs bilan savdo qilinmaydi
OUTLIER_TOLERANCE = 0.10                 # manbalar orasidagi ruxsat etilgan farq
MAX_TON_JUMP = 0.25                      # bir yangilanishda TON kursining maksimal o'zgarishi
MAX_UZS_JUMP = 0.10                      # bir yangilanishda dollar kursining maksimal o'zgarishi
ALERT_INTERVAL = 30 * 60


def describe_error(e: BaseException) -> str:
    """Logga tushunarli xato matni (timeout kabi xatolarning matni bo'sh bo'ladi)."""
    if isinstance(e, (asyncio.TimeoutError, TimeoutError)):
        return "javob kelmadi (timeout)"
    text = str(e).strip()
    if isinstance(e, RuntimeError):
        return text or type(e).__name__
    return f"{type(e).__name__}: {text}" if text else type(e).__name__


class SourceHealth:
    """Manbalar holati: xato birinchi marta (yoki matni o'zgarsa, yoki har SOURCE_LOG_REPEAT da) WARNING bo'lib
    yoziladi, tiklanganda — INFO. Shu bilan bloklangan manba har daqiqada logni to'ldirmaydi."""

    def __init__(self) -> None:
        self._down: dict[str, tuple[str, float]] = {}

    def failed(self, name: str, error: str, note: str = "") -> None:
        now = time.monotonic()
        prev = self._down.get(name)
        if prev is None or prev[0] != error or now - prev[1] >= SOURCE_LOG_REPEAT:
            log.warning("%s ishlamadi: %s%s", name, error, note)
            self._down[name] = (error, now)
        else:
            log.debug("%s ishlamadi (takror): %s", name, error)

    def recovered(self, name: str) -> None:
        if self._down.pop(name, None) is not None:
            log.info("%s yana ishlayapti", name)

    def reset(self) -> None:
        self._down.clear()


HEALTH = SourceHealth()
_cbu_retry_at = 0.0  # time.monotonic(); CBU javob bermasa, shu vaqtgacha so'ralmaydi


def reset_source_state() -> None:
    """Manbalar holatini tozalash (testlar uchun)."""
    global _cbu_retry_at
    _cbu_retry_at = 0.0
    HEALTH.reset()


async def _get_json(session: aiohttp.ClientSession, url: str, timeout: aiohttp.ClientTimeout = HTTP_TIMEOUT) -> object:
    async with session.get(url, timeout=timeout, headers=HEADERS) as resp:
        if resp.status != 200:
            raise RuntimeError(f"HTTP {resp.status}")
        return await resp.json(content_type=None)


async def _coingecko(session: aiohttp.ClientSession) -> tuple[float, float | None]:
    data = await _get_json(session, COINGECKO_URL.format(ids=f"{COINGECKO_TON_ID},{COINGECKO_USDT_ID}"))
    ton = float(data[COINGECKO_TON_ID]["usd"])  # type: ignore[index]
    usdt = (data.get(COINGECKO_USDT_ID) or {}).get("usd")  # type: ignore[union-attr]
    return ton, (float(usdt) if usdt is not None else None)


async def _binance(session: aiohttp.ClientSession) -> float:
    errors: list[str] = []
    for url in BINANCE_URLS:
        try:
            data = await _get_json(session, url)
            return float(data["price"])  # type: ignore[index]
        except Exception as e:  # noqa: BLE001
            errors.append(f"{urlsplit(url).hostname}: {describe_error(e)}")
    raise RuntimeError("; ".join(errors))


async def _kucoin(session: aiohttp.ClientSession) -> float:
    data = await _get_json(session, KUCOIN_URL)
    if str(data.get("code")) != "200000" or not data.get("data"):  # type: ignore[union-attr]
        raise RuntimeError(f"KuCoin javobi: {str(data)[:100]}")
    return float(data["data"]["price"])  # type: ignore[index]


def combine_quotes(quotes: list[tuple[float, str]], prefer: str | None = None) -> tuple[float, str]:
    """Bir nechta manbadan mediana; boshqalardan keskin farq qilganlarni chiqarib tashlaydi.
    Manbalar bir-biriga mos kelmasa — xato (yoki `prefer` berilgan bo'lsa, o'sha manba)."""
    valid = [(p, s) for p, s in quotes if p > 0]
    if not valid:
        raise RuntimeError("TON kursini olib bo'lmadi (barcha manbalar ishlamadi)")
    med = statistics.median(p for p, _ in valid)
    kept = [(p, s) for p, s in valid if abs(p / med - 1) <= OUTLIER_TOLERANCE]
    dropped = [s for p, s in valid if abs(p / med - 1) > OUTLIER_TOLERANCE]
    if not kept:
        preferred = [(p, s) for p, s in valid if s == prefer]
        if preferred:
            log.warning("Manbalar mos kelmadi, majburiy rejimda %s tanlandi: %s", prefer, valid)
            return preferred[0][0], f"{prefer} (majburiy)"
        detail = ", ".join(f"{s}={p:.4f}" for p, s in valid)
        raise RuntimeError(f"Kurs manbalari bir-biriga mos kelmadi: {detail}")
    if dropped:
        log.warning("Boshqalardan keskin farq qilgan manbalar tashlab yuborildi: %s", ", ".join(dropped))
    return statistics.median(p for p, _ in kept), "+".join(s for _, s in kept)


async def fetch_crypto_usd(session: aiohttp.ClientSession, force: bool = False) -> tuple[float, float, str]:
    """(ton_usd, usdt_usd, manbalar). `force` — admin majburan yangilaganda manbalar mos kelmasa CoinGecko olinadi."""
    results = await asyncio.gather(_coingecko(session), _binance(session), _kucoin(session), return_exceptions=True)
    quotes: list[tuple[float, str]] = []
    usdt = 1.0
    cg, bn, kc = results
    note = " (kurs qolgan manbalardan hisoblanadi)"
    if isinstance(cg, BaseException):
        HEALTH.failed("CoinGecko", describe_error(cg), note)
    else:
        HEALTH.recovered("CoinGecko")
        quotes.append((cg[0], "CoinGecko"))
        if cg[1] is not None and 0.9 <= cg[1] <= 1.1:
            usdt = cg[1]
    if isinstance(bn, BaseException):
        HEALTH.failed("Binance", describe_error(bn), note)
    else:
        HEALTH.recovered("Binance")
        quotes.append((bn, "Binance"))
    if isinstance(kc, BaseException):
        HEALTH.failed("KuCoin", describe_error(kc), note)
    else:
        HEALTH.recovered("KuCoin")
        quotes.append((kc, "KuCoin"))
    ton, sources = combine_quotes(quotes, prefer="CoinGecko" if force else None)
    return ton, usdt, sources


def _parse_cbu(data: object) -> float:
    if not isinstance(data, list) or not data:
        raise RuntimeError(f"kutilmagan javob: {str(data)[:80]}")
    return float(str(data[0]["Rate"]).replace(",", "."))


def _parse_erapi(data: object) -> float:
    return float(data["rates"]["UZS"])  # type: ignore[index]


def _parse_currency_api(data: object) -> float:
    return float(data["usd"]["uzs"])  # type: ignore[index]


async def fetch_usd_uzs(session: aiohttp.ClientSession) -> tuple[float, str]:
    """(usd_uzs, manba_nomi). Tartib: CBU (rasmiy) -> er-api -> currency-api -> currency-api (zaxira nusxa).
    CBU javob bermasa, CBU_RETRY_AFTER davomida u so'ralmaydi — kurs darhol zaxira manbadan olinadi."""
    global _cbu_retry_at
    sources: list[tuple[str, str, Callable[[object], float], aiohttp.ClientTimeout]] = [
        ("CBU", CBU_URL, _parse_cbu, CBU_TIMEOUT),
        ("er-api", ERAPI_URL, _parse_erapi, HTTP_TIMEOUT),
        ("currency-api", CURRENCY_API_URLS[0], _parse_currency_api, HTTP_TIMEOUT),
        ("currency-api (zaxira)", CURRENCY_API_URLS[1], _parse_currency_api, HTTP_TIMEOUT),
    ]
    errors: list[str] = []
    for name, url, parse, timeout in sources:
        if name == "CBU" and time.monotonic() < _cbu_retry_at:
            continue
        try:
            rate = parse(await _get_json(session, url, timeout))
            if not USD_UZS_RANGE[0] <= rate <= USD_UZS_RANGE[1]:
                raise RuntimeError(f"g'alati qiymat: {rate}")
        except Exception as e:  # noqa: BLE001
            error = describe_error(e)
            errors.append(f"{name}: {error}")
            if name == "CBU":
                _cbu_retry_at = time.monotonic() + CBU_RETRY_AFTER
                HEALTH.failed(name, error, " (dollar kursi zaxira manbadan olinadi, CBU 1 soatdan keyin qayta so'raladi)")
            else:
                HEALTH.failed(name, error)
            continue
        HEALTH.recovered(name)
        if name == "CBU":
            _cbu_retry_at = 0.0
        return rate, name

    raise RuntimeError("USD/UZS kursini olib bo'lmadi — " + "; ".join(errors))


class MarketService:
    """Joriy kurslar va zaxira (xotirada + settings jadvalida saqlanadi)."""

    def __init__(self, cfg: Config, settings: SettingsService, ton: TonService) -> None:
        self.cfg = cfg
        self.settings = settings
        self.ton = ton

        self.ton_usd: float = settings.get_float("rate_ton_usd", 0.0)
        self.usdt_usd: float = settings.get_float("rate_usdt_usd", 1.0) or 1.0
        self.usd_uzs: float = settings.get_float("rate_usd_uzs", 0.0)
        self.rates_source: str = settings.get("rates_source", "")
        self.rates_updated_at: datetime | None = self._parse_dt(settings.get("rates_updated_at"))
        self.rates_error: str = ""
        self._usd_uzs_source = ""
        self._usd_uzs_fetched = 0.0  # monotonic

        self.reserve: dict[str, int] = {
            "TON": settings.get_int("reserve_ton", 0),
            "USDT": settings.get_int("reserve_usdt", 0),
        }
        self.reserve_updated_at: datetime | None = self._parse_dt(settings.get("reserve_updated_at"))
        self.reserve_error: str = ""

        # navbatdagi (hali yuborilmagan) sotib olish arizalari uchun band qilingan miqdor
        self.pending: dict[str, int] = {"TON": 0, "USDT": 0}

        self._stock_callback: Callable[[str], Awaitable[None]] | None = None
        self._alert_callback: Callable[[str], Awaitable[None]] | None = None
        self._last_alert: float | None = None
        self._task: asyncio.Task | None = None
        self._refresh_lock = asyncio.Lock()

        # tashqi manbalarni testda almashtirish uchun
        self.fetch_crypto_usd = fetch_crypto_usd
        self.fetch_usd_uzs = fetch_usd_uzs

    @staticmethod
    def _parse_dt(text: str) -> datetime | None:
        try:
            return datetime.fromisoformat(text) if text else None
        except ValueError:
            return None

    def set_stock_callback(self, cb: Callable[[str], Awaitable[None]]) -> None:
        self._stock_callback = cb

    def set_alert_callback(self, cb: Callable[[str], Awaitable[None]]) -> None:
        self._alert_callback = cb

    async def _alert(self, text: str) -> None:
        log.warning(text)
        if self._alert_callback is None:
            return
        if self._last_alert is not None and time.monotonic() - self._last_alert < ALERT_INTERVAL:
            return
        self._last_alert = time.monotonic()
        try:
            await self._alert_callback(text)
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    #  Narxlar
    # ------------------------------------------------------------------
    def rates_fresh(self) -> bool:
        if self.rates_updated_at is None:
            return False
        return datetime.now(timezone.utc) - self.rates_updated_at <= RATE_MAX_AGE

    def has_rates(self) -> bool:
        return self.ton_usd > 0 and self.usd_uzs > 0 and self.rates_fresh()

    def market_price(self, currency: str) -> int:
        """Real kurs (so'm, 1 dona uchun). Kurs eskirgan bo'lsa 0."""
        if not self.has_rates():
            return 0
        usd = self.ton_usd if currency == "TON" else self.usdt_usd
        return int((Decimal(str(usd)) * Decimal(str(self.usd_uzs))).to_integral_value(rounding=ROUND_HALF_UP))

    def buy_price(self, currency: str) -> int:
        """Mijoz sotib oladigan narx = real kurs + ustama (so'm)."""
        m = self.market_price(currency)
        return m + self.settings.markup if m > 0 else 0

    def sell_price(self, currency: str) -> int:
        """Mijoz sotadigan narx = real kurs."""
        return self.market_price(currency)

    # ------------------------------------------------------------------
    #  Zaxira
    # ------------------------------------------------------------------
    def max_buy_units(self, currency: str) -> int:
        """Hozir sotib olish mumkin bo'lgan maksimal miqdor (units) = hamyondagi zaxira."""
        if currency == "TON":
            free = self.reserve["TON"] - MIN_GAS_RESERVE_NANO - self.pending["TON"]
            return max(0, free)
        # USDT yuborish uchun hot walletda gas (TON) bo'lishi shart
        if self.reserve["TON"] - self.pending["TON"] < MIN_GAS_RESERVE_NANO:
            return 0
        return max(0, self.reserve["USDT"] - self.pending["USDT"])

    def is_available(self, currency: str) -> bool:
        min_units = to_units(self.settings.buy_min(currency), currency)
        return self.max_buy_units(currency) >= max(min_units, 1)

    def hold(self, currency: str, units: int) -> None:
        self.pending[currency] = self.pending.get(currency, 0) + units

    def release(self, currency: str, units: int) -> None:
        self.pending[currency] = max(0, self.pending.get(currency, 0) - units)

    # ------------------------------------------------------------------
    #  Yangilash
    # ------------------------------------------------------------------
    @staticmethod
    def _jump_too_big(old: float, new: float, limit: float) -> bool:
        """Oxirgi QABUL QILINGAN kursga nisbatan (qancha vaqt o'tganidan qat'i nazar) o'zgarish chegarasi.
        Uzoq to'xtashdan keyin katta o'zgarish bo'lsa — admin bir marta majburan yangilaydi."""
        if old <= 0:
            return False
        return abs(new / old - 1) > limit

    async def refresh_rates(self, force: bool = False) -> bool:
        try:
            async with aiohttp.ClientSession() as session:
                ton_usd, usdt_usd, src1 = await self.fetch_crypto_usd(session, force=force)
                usd_uzs, src2 = self.usd_uzs, self._usd_uzs_source
                stale = (time.monotonic() - self._usd_uzs_fetched) > USD_UZS_CACHE_SECONDS
                if self.usd_uzs <= 0 or stale or not self._usd_uzs_fetched or force:
                    try:
                        usd_uzs, src2 = await self.fetch_usd_uzs(session)
                        self._usd_uzs_fetched = time.monotonic()
                        self._usd_uzs_source = src2
                    except Exception as e:  # noqa: BLE001
                        if self.usd_uzs <= 0:
                            raise
                        log.warning("USD/UZS yangilanmadi, oldingi qiymat ishlatiladi: %s", describe_error(e))
        except Exception as e:  # noqa: BLE001
            self.rates_error = describe_error(e)[:200]
            log.error("Kurs yangilanmadi: %s", self.rates_error)
            return False

        if not force:
            if self._jump_too_big(self.ton_usd, ton_usd, MAX_TON_JUMP):
                self.rates_error = f"TON kursi keskin o'zgardi: {self.ton_usd:.4f}$ -> {ton_usd:.4f}$ (qabul qilinmadi)"
                await self._alert(
                    f"⚠️ {self.rates_error}\nTekshirib, 💰 Narxlar & Miqdor → 🔄 Kurs va zaxirani hozir yangilash tugmasini bosing."
                )
                return False
            if self._jump_too_big(self.usd_uzs, usd_uzs, MAX_UZS_JUMP):
                self.rates_error = f"Dollar kursi keskin o'zgardi: {self.usd_uzs:.2f} -> {usd_uzs:.2f} (qabul qilinmadi)"
                await self._alert(
                    f"⚠️ {self.rates_error}\nTekshirib, 💰 Narxlar & Miqdor → 🔄 Kurs va zaxirani hozir yangilash tugmasini bosing."
                )
                return False

        self.rates_error = ""
        self.ton_usd, self.usdt_usd, self.usd_uzs = ton_usd, usdt_usd, usd_uzs
        self.rates_source = f"{src1} | {src2 or 'kesh'}"
        self.rates_updated_at = datetime.now(timezone.utc)
        await self.settings.set("rate_ton_usd", repr(ton_usd))
        await self.settings.set("rate_usdt_usd", repr(usdt_usd))
        await self.settings.set("rate_usd_uzs", repr(usd_uzs))
        await self.settings.set("rates_source", self.rates_source)
        await self.settings.set("rates_updated_at", self.rates_updated_at.isoformat())
        return True

    async def refresh_reserve(self) -> bool:
        try:
            ton_balance = await self.ton.get_ton_balance()
            usdt_balance = await self.ton.get_usdt_balance()
        except Exception as e:  # noqa: BLE001
            self.reserve_error = describe_error(e)[:200]
            log.error("Zaxira yangilanmadi: %s", self.reserve_error)
            return False

        self.reserve_error = ""
        self.reserve["TON"] = ton_balance
        self.reserve["USDT"] = usdt_balance
        self.reserve_updated_at = datetime.now(timezone.utc)
        await self.settings.set("reserve_ton", ton_balance)
        await self.settings.set("reserve_usdt", usdt_balance)
        await self.settings.set("reserve_updated_at", self.reserve_updated_at.isoformat())
        return True

    async def refresh_all(self, force: bool = False) -> None:
        async with self._refresh_lock:
            before = {cur: self.is_available(cur) for cur in ("TON", "USDT")}
            await self.refresh_rates(force=force)
            await self.refresh_reserve()
            if self._stock_callback is None or not self.has_rates():
                return
            for cur in ("TON", "USDT"):
                if not before[cur] and self.is_available(cur):
                    try:
                        await self._stock_callback(cur)
                    except Exception as e:  # noqa: BLE001
                        log.exception("Zaxira xabari yuborilmadi: %s", e)

    async def run_forever(self) -> None:
        """Har `rate_update_interval` (60) soniyada kurs va zaxirani yangilaydi.
        (Birinchi yangilash ishga tushishda alohida chaqiriladi.)"""
        while True:
            await asyncio.sleep(self.cfg.rate_update_interval)
            try:
                await self.refresh_all()
            except Exception as e:  # noqa: BLE001
                log.exception("Market loop xatosi: %s", e)

    def start(self) -> None:
        self._task = asyncio.create_task(self.run_forever(), name="market-loop")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

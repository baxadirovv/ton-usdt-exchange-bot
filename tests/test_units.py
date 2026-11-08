"""Yordamchi funksiyalar, .env o'qish va kurs manbalari (mahalliy soxta server bilan) testlari."""
from __future__ import annotations

import asyncio
import logging
from decimal import Decimal

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from bot import utils
from bot.config import ConfigError, load_config
from bot.services import market as market_mod
from bot.services.payments import parse_webhook_amount


def test_parse_numbers():
    assert utils.parse_decimal("1,5") == Decimal("1.5")
    assert utils.parse_decimal(" 2 ") == Decimal("2")
    assert utils.parse_decimal("0") is None
    assert utils.parse_decimal("-1") is None
    assert utils.parse_decimal("1e5") is None
    assert utils.parse_decimal("abc") is None
    assert utils.parse_decimal("0.1234567891") == Decimal("0.123456")
    assert utils.parse_int("10 000") == 10000
    assert utils.parse_int("10000.00") == 10000
    assert utils.parse_int("x") is None
    assert utils.parse_signed_int("-5 000") == -5000


def test_units_and_format():
    assert utils.to_units(Decimal("1.5"), "TON") == 1_500_000_000
    assert utils.to_units(Decimal("2.5"), "USDT") == 2_500_000
    assert utils.fmt_amount(1_500_000_000, "TON") == "1.5"
    assert utils.fmt_amount(1_000_000_000, "TON") == "1"
    assert utils.fmt_amount(123, "TON") == "0"
    assert utils.fmt_uzs(1234567) == "1 234 567 so'm"
    assert utils.fmt_uzs(-500) == "-500 so'm"
    assert utils.calc_total(Decimal("1.5"), 39400) == 59100
    assert utils.mask_card("8600123412345678") == "8600 **** **** 5678"
    assert utils.fmt_card("8600123412345678") == "8600 1234 1234 5678"
    assert utils.esc("<b>&") == "&lt;b&gt;&amp;"


def test_webhook_amount_parsing():
    assert parse_webhook_amount("541545.00") == 541545
    assert parse_webhook_amount("541545") == 541545
    assert parse_webhook_amount("541 545,00") == 541545
    assert parse_webhook_amount("541,545.00") == 541545
    assert parse_webhook_amount("0") is None
    assert parse_webhook_amount("-5") is None
    assert parse_webhook_amount("abc") is None
    assert parse_webhook_amount("") is None
    assert parse_webhook_amount("NaN") is None
    assert parse_webhook_amount("Infinity") is None


def test_config_loading(tmp_path, monkeypatch):
    keys = ("BOT_TOKEN", "ADMIN_IDS", "ADMIN_ID", "TON_MNEMONIC", "TON_WALLET_VERSION", "TON_NETWORK", "TON_MNEMONIC_TYPE",
            "PUBLIC_URL", "DATABASE_URL", "DB_HOST", "DB_PORT", "DB_USER", "DB_PASSWORD", "DB_NAME", "DB_SOCKET", "WEB_ENABLED")
    for key in keys:
        monkeypatch.delenv(key, raising=False)
    env = tmp_path / ".env"
    words = " ".join(["abandon"] * 23 + ["art"])
    env.write_text(
        f'BOT_TOKEN=123:abc\nADMIN_IDS=111, 222\nTON_MNEMONIC="{words}"\nTON_WALLET_VERSION=W5\nPUBLIC_URL=https://domen.uz/\n'
        'DB_HOST=localhost\nDB_USER=cripto_user\nDB_PASSWORD="p@ss#w:rd/1"\nDB_NAME=cripto_db\nWEB_ENABLED=false\n'
    )
    cfg = load_config(env)
    from sqlalchemy.engine import make_url
    url = make_url(cfg.database_url)
    assert url.drivername == "mysql+aiomysql" and url.password == "p@ss#w:rd/1" and url.database == "cripto_db"
    assert url.query["charset"] == "utf8mb4" and "p@ss" not in cfg.database_url_safe
    assert cfg.web_enabled is False
    assert cfg.admin_ids == (111, 222)
    assert cfg.ton_wallet_version == "v5r1"
    assert len(cfg.ton_mnemonic.split()) == 24
    assert cfg.public_url == "https://domen.uz"
    assert cfg.broadcast_per_minute == 500 and cfg.payment_timeout_minutes == 5

    for key in keys:
        monkeypatch.delenv(key, raising=False)
    bad = tmp_path / "bad.env"
    bad.write_text("BOT_TOKEN=123:abc\nADMIN_IDS=111\nTON_MNEMONIC=one two three\nDB_NAME=x\n")
    with pytest.raises(ConfigError, match="12 yoki 24"):
        load_config(bad)
    for key in keys:
        monkeypatch.delenv(key, raising=False)
    nodb = tmp_path / "nodb.env"
    nodb.write_text(f'BOT_TOKEN=123:abc\nADMIN_IDS=111\nTON_MNEMONIC="{words}"\n')
    with pytest.raises(ConfigError, match="MySQL"):
        load_config(nodb)


def test_rate_sources_median_and_outliers(monkeypatch):
    market_mod.reset_source_state()

    async def scenario():
        app = web.Application()
        state = {"cg": 1.21, "bn": 1.20, "kc": 1.22, "cg_fail": True}

        async def coingecko(request):
            if state["cg_fail"]:
                return web.Response(status=429)
            return web.json_response({"the-open-network": {"usd": state["cg"]}, "tether": {"usd": 0.999}})

        async def binance_blocked(request):  # api.binance.com ba'zi serverlarga shunday javob beradi
            return web.json_response({"code": 0, "msg": "Service unavailable from a restricted location"}, status=451)

        async def binance(request):
            return web.json_response({"symbol": "GRAMUSDT", "price": f"{state['bn']:.8f}"})

        async def kucoin(request):
            return web.json_response({"code": "200000", "data": {"price": str(state["kc"])}})

        async def cbu(request):
            return web.json_response([{"id": 69, "Code": "840", "Ccy": "USD", "Nominal": "1", "Rate": "12650.53", "Date": "27.10.2026"}])

        app.router.add_get("/cg", coingecko)
        app.router.add_get("/bn451", binance_blocked)
        app.router.add_get("/bn", binance)
        app.router.add_get("/kc", kucoin)
        app.router.add_get("/cbu", cbu)
        async with TestServer(app) as server:
            base = str(server.make_url(""))
            monkeypatch.setattr(market_mod, "COINGECKO_URL", base + "/cg?ids={ids}")
            # birinchi Binance manzili 451 qaytaradi — ikkinchisidan olinadi
            monkeypatch.setattr(market_mod, "BINANCE_URLS", (base + "/bn451", base + "/bn"))
            monkeypatch.setattr(market_mod, "KUCOIN_URL", base + "/kc")
            monkeypatch.setattr(market_mod, "CBU_URL", base + "/cbu")
            async with aiohttp.ClientSession() as session:
                # CoinGecko ishlamadi — qolgan ikkitasining medianasi
                ton, usdt, src = await market_mod.fetch_crypto_usd(session)
                assert abs(ton - 1.21) < 1e-9 and usdt == 1.0 and src == "Binance+KuCoin"
                # hammasi ishlaydi
                state["cg_fail"] = False
                ton, usdt, src = await market_mod.fetch_crypto_usd(session)
                assert ton == 1.21 and usdt == 0.999 and src == "CoinGecko+Binance+KuCoin"
                # bitta manba noto'g'ri tokenning narxini bersa — tashlab yuboriladi
                state["kc"] = 9.99
                ton, usdt, src = await market_mod.fetch_crypto_usd(session)
                assert abs(ton - 1.205) < 1e-9 and "KuCoin" not in src
                rate, src = await market_mod.fetch_usd_uzs(session)
                assert rate == 12650.53 and src == "CBU"

    asyncio.run(scenario())


def test_describe_error_never_empty():
    assert market_mod.describe_error(asyncio.TimeoutError()) == "javob kelmadi (timeout)"
    assert market_mod.describe_error(TimeoutError()) == "javob kelmadi (timeout)"
    assert market_mod.describe_error(RuntimeError("HTTP 451")) == "HTTP 451"
    assert market_mod.describe_error(KeyError("price")) == "KeyError: 'price'"
    assert market_mod.describe_error(ConnectionResetError()) == "ConnectionResetError"


def test_usd_uzs_fallback_chain_and_cbu_cooldown(monkeypatch, caplog):
    """CBU javob bermasa (chet eldagi server) — zaxira manbadan olinadi, CBU 1 soat so'ralmaydi, keyin tiklanadi."""
    caplog.set_level(logging.INFO, logger="market")
    market_mod.reset_source_state()

    async def scenario():
        app = web.Application()
        state = {"cbu_slow": True, "cbu_calls": 0, "erapi_ok": False, "cur": 12701.25}

        async def cbu(request):
            state["cbu_calls"] += 1
            if state["cbu_slow"]:
                await asyncio.sleep(1.0)
            return web.json_response([{"Ccy": "USD", "Rate": "12650.53"}])

        async def erapi(request):
            if not state["erapi_ok"]:
                return web.Response(status=500)
            return web.json_response({"result": "success", "rates": {"UZS": 12690.0}})

        async def currency_api(request):
            return web.json_response({"date": "2026-10-27", "usd": {"uzs": state["cur"], "eur": 0.86}})

        async def mirror(request):
            return web.json_response({"date": "2026-10-27", "usd": {"uzs": 12702.0}})

        app.router.add_get("/cbu", cbu)
        app.router.add_get("/erapi", erapi)
        app.router.add_get("/cur", currency_api)
        app.router.add_get("/mirror", mirror)
        async with TestServer(app) as server:
            base = str(server.make_url(""))
            monkeypatch.setattr(market_mod, "CBU_URL", base + "/cbu")
            monkeypatch.setattr(market_mod, "CBU_TIMEOUT", aiohttp.ClientTimeout(total=0.2))
            monkeypatch.setattr(market_mod, "ERAPI_URL", base + "/erapi")
            monkeypatch.setattr(market_mod, "CURRENCY_API_URLS", (base + "/cur", base + "/mirror"))
            async with aiohttp.ClientSession() as session:
                # 1) CBU timeout, er-api 500 -> currency-api
                assert await market_mod.fetch_usd_uzs(session) == (12701.25, "currency-api")
                assert state["cbu_calls"] == 1
                assert "CBU ishlamadi: javob kelmadi (timeout)" in caplog.text
                # 2) darhol yana: CBU so'ralmaydi (kutish yo'q), er-api tiklandi
                state["erapi_ok"] = True
                assert await market_mod.fetch_usd_uzs(session) == (12690.0, "er-api")
                assert state["cbu_calls"] == 1
                assert "er-api yana ishlayapti" in caplog.text
                # 3) 1 soat o'tdi va CBU tiklandi -> yana rasmiy kurs
                state["cbu_slow"] = False
                market_mod._cbu_retry_at = 0.0
                assert await market_mod.fetch_usd_uzs(session) == (12650.53, "CBU")
                assert "CBU yana ishlayapti" in caplog.text
                # 4) g'alati qiymat qabul qilinmaydi; hammasi ishlamasa — tushunarli xato
                state["cbu_slow"], state["erapi_ok"], state["cur"] = True, False, 1.0
                market_mod._cbu_retry_at = 0.0
                monkeypatch.setattr(market_mod, "CURRENCY_API_URLS", (base + "/cur", base + "/yoq"))
                with pytest.raises(RuntimeError, match="g'alati qiymat") as err:
                    await market_mod.fetch_usd_uzs(session)
                assert "CBU: javob kelmadi (timeout)" in str(err.value) and "HTTP 404" in str(err.value)

    try:
        asyncio.run(scenario())
    finally:
        market_mod.reset_source_state()


def test_blocked_source_is_logged_once_not_every_minute(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="market")
    market_mod.reset_source_state()

    async def scenario():
        app = web.Application()
        state = {"blocked": True}

        async def coingecko(request):
            return web.json_response({"the-open-network": {"usd": 1.21}, "tether": {"usd": 1.0}})

        async def binance(request):
            if state["blocked"]:
                return web.Response(status=451)
            return web.json_response({"symbol": "GRAMUSDT", "price": "1.20000000"})

        async def kucoin(request):
            return web.json_response({"code": "200000", "data": {"price": "1.22"}})

        app.router.add_get("/cg", coingecko)
        app.router.add_get("/bn", binance)
        app.router.add_get("/kc", kucoin)
        async with TestServer(app) as server:
            base = str(server.make_url(""))
            monkeypatch.setattr(market_mod, "COINGECKO_URL", base + "/cg?ids={ids}")
            monkeypatch.setattr(market_mod, "BINANCE_URLS", (base + "/bn", base + "/bn"))
            monkeypatch.setattr(market_mod, "KUCOIN_URL", base + "/kc")
            async with aiohttp.ClientSession() as session:
                for _ in range(5):  # 5 daqiqa
                    ton, _usdt, src = await market_mod.fetch_crypto_usd(session)
                    assert abs(ton - 1.215) < 1e-9 and src == "CoinGecko+KuCoin"
                warnings = [r for r in caplog.records if r.levelno == logging.WARNING and "Binance" in r.getMessage()]
                assert len(warnings) == 1 and "HTTP 451" in warnings[0].getMessage()
                state["blocked"] = False
                ton, _usdt, src = await market_mod.fetch_crypto_usd(session)
                assert src == "CoinGecko+Binance+KuCoin" and "Binance yana ishlayapti" in caplog.text

    asyncio.run(scenario())


def test_market_jump_guard_and_staleness():
    from datetime import datetime, timedelta, timezone

    from tests.harness import make_env

    async def scenario():
        env = await make_env()
        try:
            m = env.market
            assert m.has_rates() and m.market_price("TON") == 38_400
            alerts: list[str] = []

            async def alert(text):
                alerts.append(text)

            m.set_alert_callback(alert)

            async def jump(_s, force=False):
                return 6.0, 1.0, "test"  # 3.0 -> 6.0 (+100%)

            m.fetch_crypto_usd = jump
            await m.refresh_all()
            assert m.ton_usd == 3.0 and alerts and "keskin" in alerts[0]
            await m.refresh_all(force=True)  # admin majburan yangiladi
            assert m.ton_usd == 6.0

            # kurs 10 daqiqadan eski — savdo to'xtaydi
            m.rates_updated_at = datetime.now(timezone.utc) - timedelta(minutes=11)
            assert not m.has_rates() and m.buy_price("TON") == 0 and m.sell_price("USDT") == 0
        finally:
            await env.close()

    asyncio.run(scenario())


def test_combine_quotes_disagreement_and_force():
    with pytest.raises(RuntimeError, match="mos kelmadi"):
        market_mod.combine_quotes([(1.0, "CoinGecko"), (1.5, "Binance")])
    assert market_mod.combine_quotes([(1.0, "CoinGecko"), (1.5, "Binance")], prefer="CoinGecko") == (1.0, "CoinGecko (majburiy)")
    assert market_mod.combine_quotes([(1.0, "A"), (1.02, "B"), (5.0, "C")]) == (1.01, "A+B")
    with pytest.raises(RuntimeError):
        market_mod.combine_quotes([])


def test_jump_cap_does_not_lapse_after_long_pause():
    from datetime import datetime, timedelta, timezone

    from tests.harness import make_env

    async def scenario():
        env = await make_env()
        try:
            m = env.market
            m.rates_updated_at = datetime.now(timezone.utc) - timedelta(days=3)  # bot uzoq to'xtagan

            async def jump(_s, force=False):
                return 6.0, 1.0, "test"

            m.fetch_crypto_usd = jump
            assert await m.refresh_rates() is False and m.ton_usd == 3.0
            assert await m.refresh_rates(force=True) is True and m.ton_usd == 6.0
        finally:
            await env.close()

    asyncio.run(scenario())


def test_repo_functions_wrapped_with_db_retry():
    """Barcha ochiq async repo funksiyalari MySQL deadlock'da qayta urinadi (Python 3.12.x import xatosi regressiyasi)."""
    import inspect

    from bot.db import repo as repo_mod

    public = [
        name for name, obj in vars(repo_mod).items()
        if not name.startswith("_") and inspect.isfunction(obj)
        and obj.__module__ == repo_mod.__name__ and inspect.iscoroutinefunction(obj)
    ]
    assert len(public) > 30
    assert all(hasattr(getattr(repo_mod, name), "__wrapped__") for name in public)

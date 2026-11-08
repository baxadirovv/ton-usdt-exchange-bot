"""main() ni to'liq ishga tushirish (faqat Telegram transporti soxta, TON/kurs tarmog'i mavjud emas)."""
from __future__ import annotations

import asyncio
import socket

import aiohttp
from aiogram import Bot
from ton_core import ton_mnemonic_new

import bot.app as app_mod
from bot.config import DEFAULT_USDT_MASTER, Config
from tests import harness
from tests.harness import FakeSession


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_main_starts_and_stops(tmp_path, monkeypatch):
    port = free_port()
    cfg = Config(
        bot_token="123456:TEST", admin_ids=(1,),
        database_url=harness.TEST_DB if harness.IS_MYSQL else f"sqlite+aiosqlite:///{tmp_path}/bot.db",
        ton_network="mainnet", ton_mnemonic=" ".join(ton_mnemonic_new()), ton_wallet_version="v5r1",
        ton_mnemonic_type="auto", toncenter_api_key=None, usdt_jetton_master=DEFAULT_USDT_MASTER,
        web_host="127.0.0.1", web_port=port, public_url="https://domen.uz", rate_update_interval=60,
        payment_timeout_minutes=5, broadcast_per_minute=500, timezone="Asia/Tashkent",
    )
    session = FakeSession()
    captured = {}

    def fake_build():
        # routerlar bitta jarayonda faqat bir marta ulanadi — test muhitidagi tayyor Dispatcher'dan foydalanamiz
        from aiogram.fsm.storage.memory import MemoryStorage, SimpleEventIsolation

        harness.DP.fsm.storage = MemoryStorage()
        harness.DP.fsm.events_isolation = SimpleEventIsolation()
        harness.DP.workflow_data.clear()
        captured["dp"] = harness.DP
        return harness.DP

    monkeypatch.setattr(app_mod, "load_config", lambda: cfg)
    monkeypatch.setattr(app_mod, "Bot", lambda token, default=None: Bot(token, session=session, default=default))
    monkeypatch.setattr(app_mod, "build_dispatcher", fake_build)
    monkeypatch.setattr(app_mod, "setup_logging", lambda: None)

    monkeypatch.setattr(app_mod, "BASE_DIR", tmp_path)  # qulf fayli vaqtinchalik papkada

    async def scenario():
        if harness.IS_MYSQL:
            await harness.prepare_test_db()
            from bot.db.session import dispose_engine
            await dispose_engine()
        main_task = asyncio.create_task(app_mod.main())
        health = None
        for _ in range(200):
            await asyncio.sleep(0.1)
            if any("Bot ishga tushdi" in t for t in session.sent(1)):
                async with aiohttp.ClientSession() as http:
                    async with http.get(f"http://127.0.0.1:{port}/health") as r:
                        health = await r.json()
                    async with http.get(f"http://127.0.0.1:{port}/pay", params={"miqdor": "1000", "secret_key": "bad"}) as r:
                        assert r.status == 403
                break
        assert health == {"ok": True, "service": "ton-exchange-bot"}
        report = [t for t in session.sent(1) if "Bot ishga tushdi" in t][0]
        assert "TONCENTER_API_KEY yo'q" in report and "https://domen.uz/pay" in report
        assert any(type(m).__name__ == "SetMyCommands" for m in session.requests)
        await captured["dp"].stop_polling()
        await asyncio.wait_for(main_task, timeout=30)

    asyncio.run(scenario())

"""Hosting qismi testlari: public/pay.php (haqiqiy PHP + MySQL), pay_inbox navbati, yagona nusxa qulfi,
maxfiy fayllar ochiqligini aniqlash."""
from __future__ import annotations

import asyncio
import json
import shutil
import socket
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from sqlalchemy import select
from sqlalchemy.engine import make_url

from bot import texts
from bot.db import repo
from bot.db.models import PayInbox
from bot.db.session import session_scope
from bot.runtime import acquire_single_instance_lock, find_exposed_files
from tests.harness import IS_MYSQL, TEST_DB, make_env

ROOT = Path(__file__).resolve().parent.parent
USER = 5001


def run(coro):
    return asyncio.run(coro)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def http(url: str, data: bytes | None = None, headers: dict | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(url, data=data, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")


async def inbox_rows() -> list[PayInbox]:
    async with session_scope() as s:
        return list((await s.execute(select(PayInbox).order_by(PayInbox.id))).scalars().all())


def test_inbox_processing_is_exactly_once():
    async def scenario():
        env = await make_env()
        try:
            await env.send(USER, "/start")
            await env.send(USER, texts.BTN_TOPUP)
            await env.send(USER, "20000")
            await repo.add_inbox("20000.00", "CardXabarBot")
            await repo.add_inbox("20000.00", "CardXabarBot")   # takroriy SMS
            await repo.add_inbox("abc", "CardXabarBot")
            assert await env.payments.process_inbox_once() == 3
            assert (await repo.get_user(USER)).balance == 20000
            assert [r.result for r in await inbox_rows()] == ["matched", "not_found", "bad_amount"]
            assert any("To'lov qabul qilindi" in t for t in env.session.sent(USER))
            assert await env.payments.process_inbox_once() == 0
        finally:
            await env.close()
    run(scenario())


@pytest.mark.skipif(not IS_MYSQL or shutil.which("php") is None, reason="PHP va MySQL (TEST_DATABASE_URL) kerak")
def test_php_pay_endpoint_end_to_end(tmp_path):
    url = make_url(TEST_DB)
    project = tmp_path / "cripto.smm-api.uz"
    (project / "public").mkdir(parents=True)
    shutil.copy(ROOT / "public" / "pay.php", project / "public" / "pay.php")
    password = (url.password or "").replace("\\", "\\\\").replace('"', '\\"')
    (project / ".env").write_text(
        "# test\n"
        f"DB_HOST={url.host}\nDB_PORT={url.port or 3306}\nDB_USER={url.username}\n"
        f'DB_PASSWORD="{password}"   # izoh\n'
        f"DB_NAME={url.database}\n"
    )
    port = free_port()
    proc = subprocess.Popen(
        ["php", "-S", f"127.0.0.1:{port}", "-t", str(project / "public")],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}/pay.php"

    for _ in range(50):   # PHP server ishga tushishini kutish
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)

    async def scenario():
        env = await make_env()
        try:
            secret = env.settings.get("pay_secret_key")
            await env.send(USER, "/start")
            await env.send(USER, texts.BTN_TOPUP)
            await env.send(USER, "30000")

            def q(**params):
                return base + "?" + urllib.parse.urlencode(params)

            code, body = await asyncio.to_thread(http, q(miqdor="30000.00", method="CardXabarBot", secret_key="noto'g'ri"))
            assert code == 403 and body["ok"] is False
            code, body = await asyncio.to_thread(http, q(miqdor="<script>", method="CardXabarBot", secret_key=secret))
            assert code == 400
            code, body = await asyncio.to_thread(http, q(miqdor="30000.00", method="CardXabarBot", secret_key=secret))
            assert code == 200 and body["queued"] is True and body["id"] > 0
            # POST (JSON) ham ishlaydi
            payload = json.dumps({"miqdor": "777", "method": "CardXabarBot", "secret_key": secret}).encode()
            code, body = await asyncio.to_thread(http, base, payload, {"Content-Type": "application/json"})
            assert code == 200 and body["queued"] is True

            rows = await inbox_rows()
            assert [r.raw_amount for r in rows] == ["30000.00", "777"] and rows[0].status == "new"
            assert await env.payments.process_inbox_once() == 2
            assert (await repo.get_user(USER)).balance == 30000
            assert [r.result for r in await inbox_rows()] == ["matched", "not_found"]

            # sozlash xatolari aniq javob beradi (maxfiy ma'lumot oshkor qilinmaydi)
            env_file = project / ".env"
            good = env_file.read_text()
            env_file.write_text(good.replace(f'DB_PASSWORD="{password}"', 'DB_PASSWORD="notogri"'))
            code, body = await asyncio.to_thread(http, q(miqdor="1", method="x", secret_key=secret))
            assert code == 503 and body["error"] == "database unavailable"
            env_file.unlink()
            code, body = await asyncio.to_thread(http, q(miqdor="1", method="x", secret_key=secret))
            assert code == 500 and ".env" in body["error"]
            env_file.write_text(good)
            code, body = await asyncio.to_thread(http, q(miqdor="1", method="x", secret_key=secret))
            assert code == 200 and body["queued"] is True
        finally:
            await env.close()

    try:
        run(scenario())
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_single_instance_lock(tmp_path):
    first = acquire_single_instance_lock(tmp_path / "data" / "bot.lock")
    assert first is not None
    second = acquire_single_instance_lock(tmp_path / "data" / "bot.lock")
    assert second is None
    first.close()
    third = acquire_single_instance_lock(tmp_path / "data" / "bot.lock")
    assert third is not None
    third.close()


def test_exposure_detector():
    async def scenario():
        app = web.Application()
        state = {"open": True, "redirect": False}

        async def env_file(request):
            if state["redirect"]:  # masalan http -> https yo'naltirish
                raise web.HTTPMovedPermanently("/real/.env")
            if state["open"]:
                return web.Response(text="BOT_TOKEN=1:x\nTON_MNEMONIC=word word\n")
            return web.Response(status=403, text="Forbidden")

        async def real_env(request):
            return web.Response(text="BOT_TOKEN=1:x\nTON_MNEMONIC=word word\n")

        async def forbidden(request):
            return web.Response(status=403)

        app.router.add_get("/.env", env_file)
        app.router.add_get("/real/.env", real_env)
        app.router.add_get("/{tail:.*}", forbidden)
        async with TestServer(app) as server:
            base = str(server.make_url("")).rstrip("/")
            stats: dict = {}
            assert await find_exposed_files(base, allow_local=True, stats=stats) == ["/.env"]
            assert stats == {"reached": 4, "skipped": False}
            state["open"] = False
            assert await find_exposed_files(base, allow_local=True, stats=stats) == []
            assert stats["reached"] == 4  # server javob berdi — fayllar yopiq
            state["redirect"] = True     # yo'naltirish ortidagi ochiq fayl ham topiladi
            assert await find_exposed_files(base, allow_local=True) == ["/.env"]
            assert await find_exposed_files(base, stats=stats) == []  # localhost — sukut bo'yicha tekshirilmaydi
            assert stats["skipped"] is True
        # server o'chiq — "yopiq" deb emas, "ulanib bo'lmadi" deb hisoblanadi
        stats = {}
        assert await find_exposed_files(base, allow_local=True, timeout=2, stats=stats) == []
        assert stats == {"reached": 0, "skipped": False}

    run(scenario())

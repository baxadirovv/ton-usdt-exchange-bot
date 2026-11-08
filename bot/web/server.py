"""
To'lov xabarlarini qabul qiluvchi HTTP server.

  GET/POST /pay?miqdor=541545.00&method=CardXabarBot&secret_key=KALIT

Javoblar (JSON):
  200 {"ok": true, "matched": true, "payment_id": 12}   — chek topildi, balans to'ldirildi
  200 {"ok": true, "matched": false}                     — bu summada chek yo'q (adminga xabar ketadi)
  400 {"ok": false, "error": "invalid amount"}
  403 {"ok": false, "error": "invalid secret_key"}
"""
from __future__ import annotations

import hmac
import logging

from aiohttp import web

from ..services.payments import PaymentService
from ..services.settings import SettingsService

log = logging.getLogger("web")

PAYMENTS_KEY = web.AppKey("payments", PaymentService)
SETTINGS_KEY = web.AppKey("settings", SettingsService)


async def _collect_params(request: web.Request) -> dict[str, str]:
    params: dict[str, str] = {k: v for k, v in request.query.items()}
    if request.method == "POST":
        try:
            if request.content_type == "application/json":
                body = await request.json()
                if isinstance(body, dict):
                    for k, v in body.items():
                        params.setdefault(str(k), "" if v is None else str(v))
            else:
                form = await request.post()
                for k, v in form.items():
                    if isinstance(v, str):
                        params.setdefault(k, v)
        except Exception as e:  # noqa: BLE001
            log.warning("POST tanasini o'qib bo'lmadi: %s", e)
    return params


async def pay_handler(request: web.Request) -> web.Response:
    payments: PaymentService = request.app[PAYMENTS_KEY]
    settings: SettingsService = request.app[SETTINGS_KEY]

    params = await _collect_params(request)
    expected = settings.get("pay_secret_key")
    given = params.get("secret_key", "")
    if not expected or not hmac.compare_digest(given.encode("utf-8"), expected.encode("utf-8")):
        log.warning("Noto'g'ri secret_key bilan /pay so'rovi (%s)", request.remote)
        return web.json_response({"ok": False, "error": "invalid secret_key"}, status=403)

    raw_amount = params.get("miqdor") or params.get("amount") or ""
    method = params.get("method") or None
    try:
        status, payment = await payments.process_incoming(raw_amount, method)
    except Exception as e:  # noqa: BLE001
        log.exception("/pay ichki xato: %s", e)
        return web.json_response({"ok": False, "error": "internal error"}, status=500)

    if status == "bad_amount":
        return web.json_response({"ok": False, "error": "invalid amount"}, status=400)
    if status == "not_found" or payment is None:
        return web.json_response({"ok": True, "matched": False})
    return web.json_response({"ok": True, "matched": True, "payment_id": payment.id})


async def health_handler(_request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "service": "ton-exchange-bot"})


def create_app(payments: PaymentService, settings: SettingsService) -> web.Application:
    app = web.Application(client_max_size=64 * 1024)
    app[PAYMENTS_KEY] = payments
    app[SETTINGS_KEY] = settings
    app.router.add_route("GET", "/pay", pay_handler)
    app.router.add_route("POST", "/pay", pay_handler)
    app.router.add_route("GET", "/pay/", pay_handler)
    app.router.add_route("POST", "/pay/", pay_handler)
    app.router.add_get("/", health_handler)
    app.router.add_get("/health", health_handler)
    return app


async def start_web(app: web.Application, host: str, port: int) -> web.AppRunner:
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, host=host, port=port)
    await site.start()
    log.info("To'lov serveri ishga tushdi: http://%s:%s/pay", host, port)
    return runner

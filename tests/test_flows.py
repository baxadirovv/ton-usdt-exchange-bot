"""
To'liq oqim testlari: haqiqiy Dispatcher + handlerlar + baza, soxta Telegram va soxta TON.
Ishga tushirish:  python -m pytest -q tests
"""
from __future__ import annotations

import asyncio
import time
from datetime import timedelta

from sqlalchemy import select, update

from bot import texts
from bot.callbacks import (
    AdmBroadcastCB,
    AdmChanCB,
    AdmOrderCB,
    AdmSellCB,
    AdmSetCB,
    AdmUserCB,
    BuyConfirmCB,
    ExchangeCB,
    GuideCB,
    HistoryCB,
    SimpleCB,
    StockAlertCB,
    TopupCB,
)
from bot.db import repo
from bot.db.models import Order, Payment, Profit, User, utcnow
from bot.db.session import session_scope
from bot.services.ton import SendResult
from tests.harness import ADMIN_ID, HOT_WALLET, make_env, new_address

USER = 1001
USER2 = 1002
USER3 = 1003


def run(coro):
    return asyncio.run(coro)


async def give_balance(uid: int, amount: int) -> None:
    async with session_scope() as s:
        await s.execute(update(User).where(User.id == uid).values(balance=amount))


async def balance(uid: int) -> int:
    u = await repo.get_user(uid)
    return u.balance if u else -1


# =====================================================================
#  /start, menyu, referal
# =====================================================================
def test_start_menu_and_admin_button():
    async def scenario():
        env = await make_env()
        try:
            await env.send(USER, "/start", name="Ali")
            m = env.session.last_method("SendMessage", USER)
            assert "Assalomu alaykum" in m.text and "Ali" in m.text
            buttons = [b.text for row in m.reply_markup.keyboard for b in row]
            assert texts.BTN_EXCHANGE in buttons and texts.BTN_ADMIN not in buttons

            await env.send(ADMIN_ID, "/start")
            m = env.session.last_method("SendMessage", ADMIN_ID)
            buttons = [b.text for row in m.reply_markup.keyboard for b in row]
            assert texts.BTN_ADMIN in buttons

            # oddiy foydalanuvchi admin panelga kira olmaydi
            await env.send(USER, texts.BTN_ADMIN)
            assert env.session.last(USER) == texts.NOT_ADMIN
            await env.send(ADMIN_ID, texts.BTN_ADMIN)
            assert "Admin panel" in env.session.last(ADMIN_ID)
        finally:
            await env.close()
    run(scenario())


def test_referral_without_channels():
    async def scenario():
        env = await make_env()
        try:
            await env.send(USER, "/start")
            await env.send(USER2, f"/start ref{USER}", name="Vali")
            u2 = await repo.get_user(USER2)
            assert u2.referrer_id == USER and u2.ref_credited
            assert any("yangi referal" in t and "Vali" in t for t in env.session.sent(USER))
            # o'zini o'zi taklif qila olmaydi, mavjud foydalanuvchi o'zgarmaydi
            await env.send(USER3, f"/start ref{USER3}")
            assert (await repo.get_user(USER3)).referrer_id is None
            await env.send(USER2, f"/start ref{USER3}")
            assert (await repo.get_user(USER2)).referrer_id == USER
            assert await repo.count_referrals(USER) == 1

            env.session.clear()
            await env.send(USER, texts.BTN_REFERRAL)
            m = env.session.last_method("SendMessage", USER)
            assert f"https://t.me/test_bot?start=ref{USER}" in m.text
            assert "1 ta" in m.text and "2%" in m.text
            url = m.reply_markup.inline_keyboard[0][0].url
            assert url.startswith("https://t.me/share/url?url=")
        finally:
            await env.close()
    run(scenario())


# =====================================================================
#  Balans to'ldirish + /pay
# =====================================================================
def test_topup_unique_amounts_and_webhook():
    async def scenario():
        env = await make_env()
        try:
            for uid in (USER, USER2):
                await env.send(uid, "/start")
            await env.send(USER, texts.BTN_TOPUP)
            assert "qancha to'ldirmoqchisiz" in env.session.last(USER)
            await env.send(USER, "500")  # minimaldan kam
            assert "dan" in env.session.last(USER) and "gacha" in env.session.last(USER)
            await env.send(USER, "20 000")
            invoice1 = env.session.last(USER)
            assert "20 000 so'm" in invoice1 and "8600 1234 1234 1234" in invoice1 and "ALI VALIYEV" in invoice1

            await env.send(USER2, texts.BTN_TOPUP)
            await env.send(USER2, "20000")
            invoice2 = env.session.last(USER2)
            p2 = await repo.get_active_payment(USER2)
            assert 20001 <= p2.amount <= 20050, p2.amount
            assert "qo'shildi" in invoice2 and f"Aynan {p2.amount:,}".replace(",", " ") in invoice2

            # ikkinchi chek yaratib bo'lmaydi
            await env.send(USER, texts.BTN_TOPUP)
            assert "tugallanmagan" in env.session.last(USER)

            # --- /pay webhook ---
            from aiohttp.test_utils import TestClient, TestServer

            from bot.web.server import create_app

            secret = env.settings.get("pay_secret_key")
            async with TestClient(TestServer(create_app(env.payments, env.settings))) as client:
                r = await client.get("/pay", params={"miqdor": "20000.00", "method": "CardXabarBot", "secret_key": "wrong"})
                assert r.status == 403
                r = await client.get("/pay", params={"miqdor": "abc", "method": "CardXabarBot", "secret_key": secret})
                assert r.status == 400
                r = await client.get("/pay", params={"miqdor": "20000.00", "method": "CardXabarBot", "secret_key": secret})
                data = await r.json()
                assert r.status == 200 and data["matched"] is True
                assert await balance(USER) == 20000
                assert any("To'lov qabul qilindi" in t for t in env.session.sent(USER))
                # takroriy xabar — ikkinchi marta qo'shilmaydi
                r = await client.get("/pay", params={"miqdor": "20000.00", "method": "CardXabarBot", "secret_key": secret})
                assert (await r.json())["matched"] is False
                assert await balance(USER) == 20000
                # POST (form) ham ishlaydi
                r = await client.post("/pay", data={"miqdor": f"{p2.amount}.00", "method": "CardXabarBot", "secret_key": secret})
                assert (await r.json())["matched"] is True
                assert await balance(USER2) == p2.amount
            u = await repo.get_user(USER)
            assert u.total_topup == 20000
        finally:
            await env.close()
    run(scenario())


def test_topup_cancel_expire_and_late_payment():
    async def scenario():
        env = await make_env()
        try:
            await env.send(USER, "/start")
            await env.send(USER, texts.BTN_TOPUP)
            await env.send(USER, "15000")
            p = await repo.get_active_payment(USER)
            await env.click(USER, TopupCB(action="cancel", payment_id=p.id).pack())
            assert "BEKOR QILINDI" in env.session.last(USER)
            assert await repo.get_active_payment(USER) is None

            # yangi chek -> muddati o'tadi
            await env.send(USER, texts.BTN_TOPUP)
            await env.send(USER, "15000")
            p2 = await repo.get_active_payment(USER)
            assert p2.amount != p.amount  # 30 daqiqa ichida summa takrorlanmaydi
            async with session_scope() as s:
                await s.execute(update(Payment).where(Payment.id == p2.id).values(expires_at=utcnow() - timedelta(seconds=1)))
            expired = await env.payments.expire_once()
            assert [x.id for x in expired] == [p2.id]
            assert texts.TOPUP_EXPIRED in env.session.sent(USER)

            # foydalanuvchi kechikib to'ladi — baribir balansga tushadi
            status, paid = await env.payments.process_incoming(f"{p2.amount}.00", "CardXabarBot")
            assert status == "matched" and paid.id == p2.id
            assert await balance(USER) == p2.amount
        finally:
            await env.close()
    run(scenario())


def test_topup_not_configured():
    async def scenario():
        env = await make_env()
        try:
            await env.settings.set("card_number", "")
            await env.send(USER, "/start")
            await env.send(USER, texts.BTN_TOPUP)
            assert env.session.last(USER) == texts.TOPUP_NOT_CONFIGURED
        finally:
            await env.close()
    run(scenario())


# =====================================================================
#  Sotib olish (avtomatik yuborish)
# =====================================================================
def test_buy_ton_full_flow_with_referral_profit_and_history_channel():
    async def scenario():
        env = await make_env()
        try:
            await env.settings.set("history_channel", "-1001234567890")
            await env.send(USER, "/start")
            await env.send(USER2, f"/start ref{USER}", name="Bobur")
            await give_balance(USER2, 100_000)

            await env.send(USER2, texts.BTN_EXCHANGE)
            menu_text = env.session.last(USER2)
            assert "39 400 so'm" in menu_text and "38 400 so'm" in menu_text  # TON: 38400 + 1000 ustama

            await env.click(USER2, ExchangeCB(action="buy", currency="TON").pack())
            ask = env.session.last(USER2)
            assert "39 400 so'm" in ask and "2.538" in ask  # balansga yetadi: 100000/39400
            assert "99.9" in ask  # maksimal = 100 TON - 0.1 gas zaxira

            await env.send(USER2, "abc")
            assert env.session.last(USER2) == texts.INVALID_AMOUNT
            await env.send(USER2, "0.01")
            assert "Minimal" in env.session.last(USER2)
            await env.send(USER2, "500")
            assert "maksimal" in env.session.last(USER2)
            await env.send(USER2, "3")  # 118 200 > 100 000
            assert "yetarli emas" in env.session.last(USER2)
            await env.send(USER2, "1,5")  # vergul ham ishlaydi
            assert "hamyon manzilingizni" in env.session.last(USER2)

            await env.send(USER2, "salom")
            assert env.session.last(USER2) == texts.INVALID_ADDRESS
            dest = new_address()
            await env.send(USER2, dest)
            confirm = env.session.last(USER2)
            assert "1.5 TON" in confirm and "59 100 so'm" in confirm and dest in confirm

            await env.click(USER2, BuyConfirmCB(action="ok").pack())
            assert await balance(USER2) == 100_000 - 59_100
            await env.drain()

            assert env.ton.sent[0][0] == "TON" and env.ton.sent[0][1] == dest and env.ton.sent[0][2] == 1_500_000_000
            done_text = env.session.last(USER2)
            assert "raqamli so'rovingiz bajarildi" in done_text and "1.5 ta TON" in done_text

            order = (await repo.list_user_orders(USER2, 0))[0][0]
            assert order.status == "done" and order.price == 39400 and order.market_price == 38400
            # referal bonusi: 2% * 59 100 = 1 182
            assert await balance(USER) == 1182
            assert any("bonus" in t for t in env.session.sent(USER))
            async with session_scope() as s:
                profit = (await s.execute(select(Profit))).scalars().one()
            assert profit.amount_uzs == 1500 - 1182  # ustama 1.5*1000 - bonus
            # tarix kanaliga faqat ism (username/ID yo'q)
            post = env.session.last(-1001234567890)
            assert "Bobur" in post and str(USER2) not in post and "1.5 TON" in post
            # zaxira band qilinmagan holatga qaytdi
            assert env.market.pending["TON"] == 0
        finally:
            await env.close()
    run(scenario())


def test_buy_usdt_and_double_click_protection():
    async def scenario():
        env = await make_env()
        try:
            await env.send(USER, "/start")
            await give_balance(USER, 1_000_000)
            await env.click(USER, ExchangeCB(action="buy", currency="USDT").pack())
            await env.send(USER, "10")
            await env.send(USER, new_address())
            # ikki marta bir vaqtda bosish
            await asyncio.gather(
                env.click(USER, BuyConfirmCB(action="ok").pack()),
                env.click(USER, BuyConfirmCB(action="ok").pack()),
            )
            await env.drain()
            orders, total = await repo.list_user_orders(USER, 0)
            assert total == 1, "faqat bitta ariza yaratilishi kerak"
            assert orders[0].currency == "USDT" and orders[0].amount_units == 10_000_000
            assert await balance(USER) == 1_000_000 - 10 * (12800 + 1000)
            assert env.ton.sent[0][0] == "USDT" and env.ton.sent[0][4] == orders[0].id  # query_id = ariza ID
            assert "10 ta USDT" in env.session.last(USER)
        finally:
            await env.close()
    run(scenario())


def test_buy_failed_refund_and_unknown_resolution():
    async def scenario():
        env = await make_env()
        try:
            await env.send(USER, "/start")
            await give_balance(USER, 200_000)

            async def buy(amount: str):
                await env.click(USER, ExchangeCB(action="buy", currency="TON").pack())
                await env.send(USER, amount)
                await env.send(USER, new_address())
                await env.click(USER, BuyConfirmCB(action="ok").pack())
                await env.drain()

            env.ton.result = SendResult("failed", reason="Hot walletda TON yetarli emas")
            await buy("1")
            assert await balance(USER) == 200_000  # qaytarildi
            assert "qaytarildi" in env.session.last(USER)

            env.ton.result = SendResult("unknown", "ee" * 32, "tekshiruv ishlamadi")
            await buy("1")
            assert await balance(USER) == 200_000 - 39_400
            orders, _ = await repo.list_user_orders(USER, 0)
            unknown = orders[0]
            assert unknown.status == "unknown"
            admin_msg = env.session.last_method("SendMessage", ADMIN_ID)
            assert "noaniq" in admin_msg.text and admin_msg.reply_markup is not None

            # xabar muddati tugamaguncha qaytarib bo'lmaydi
            await env.click(ADMIN_ID, AdmOrderCB(action="refund", order_id=unknown.id).pack())
            assert await balance(USER) == 200_000 - 39_400
            async with session_scope() as s:
                await s.execute(update(Order).where(Order.id == unknown.id).values(msg_valid_until=int(time.time()) - 100))
            await env.click(ADMIN_ID, AdmOrderCB(action="refund", order_id=unknown.id).pack())
            assert await balance(USER) == 200_000
            assert "qaytarildi" in env.session.last(USER)
            # ikkinchi bosish hech narsa qilmaydi
            await env.click(ADMIN_ID, AdmOrderCB(action="done", order_id=unknown.id).pack())
            assert await balance(USER) == 200_000
            assert "allaqachon" in " ".join(env.session.alerts())
        finally:
            await env.close()
    run(scenario())


def test_out_of_stock_alert_and_buy_disabled():
    async def scenario():
        env = await make_env()
        try:
            await env.send(USER, "/start")
            env.ton.usdt_balance = 0
            await env.market.refresh_all()
            await env.click(USER, ExchangeCB(action="buy", currency="USDT").pack())
            assert "qolmagan" in env.session.last(USER)
            await env.click(USER, StockAlertCB(currency="USDT").pack())
            assert "xabar beriladi" in env.session.last(USER)
            await env.click(USER, StockAlertCB(currency="USDT").pack())
            assert "allaqachon" in env.session.last(USER)

            notified: list[str] = []

            async def cb(cur):
                ids = await repo.pop_stock_alerts(cur)
                for uid in ids:
                    await env.notifier.user(uid, texts.stock_arrived(cur, env.market.max_buy_units(cur), env.market.buy_price(cur)))
                notified.append(cur)

            env.market.set_stock_callback(cb)
            env.ton.usdt_balance = 250 * 10**6
            await env.market.refresh_all()
            assert notified == ["USDT"]
            msg = env.session.last(USER)
            assert "USDT yana keldi" in msg and "250 USDT" in msg and "13 800 so'm" in msg
            assert await repo.pop_stock_alerts("USDT") == []  # bir martalik

            # sotuv o'chirilgan
            await env.settings.set("buy_enabled", "0")
            env.session.clear()
            await env.click(USER, ExchangeCB(action="buy", currency="TON").pack())
            assert texts.BUY_DISABLED in env.session.alerts()
            # sotish esa ishlaydi
            await env.click(USER, ExchangeCB(action="sell", currency="TON").pack())
            assert "sotish" in env.session.last(USER).lower()
        finally:
            await env.close()
    run(scenario())


# =====================================================================
#  Sotish (admin tasdiqlaydi)
# =====================================================================
def test_sell_flow_approve_and_cancel():
    async def scenario():
        env = await make_env(admin_ids=(ADMIN_ID, 2))
        try:
            await env.send(USER, "/start")
            await env.send(USER2, f"/start ref{USER}")
            await env.click(USER2, ExchangeCB(action="sell", currency="USDT").pack())
            ask = env.session.last(USER2)
            assert "Bot sizdan sotib olish kursi: <b>12 800 so'm</b>" in ask
            await env.send(USER2, "0.5")
            assert "gacha" in env.session.last(USER2)
            await env.send(USER2, "10")
            wallet_msg = env.session.last(USER2)
            assert HOT_WALLET in wallet_msg and "128 000 so'm" in wallet_msg and "skrinshot" in wallet_msg
            await env.send(USER2, "mana")
            assert env.session.last(USER2) == texts.SELL_NEED_PHOTO
            await env.send(USER2, photo=True)
            assert "karta raqamingizni" in env.session.last(USER2)
            await env.send(USER2, "8600 1234")
            assert env.session.last(USER2) == texts.SELL_INVALID_CARD
            await env.send(USER2, "8600 1234 5678 9012")
            assert "arizangiz qabul qilindi" in env.session.last(USER2)

            photo_to_admin = env.session.last_method("SendPhoto", ADMIN_ID)
            assert photo_to_admin.photo == "PHOTO_BIG" and "8600 1234 5678 9012" in photo_to_admin.caption
            assert env.session.last_method("SendPhoto", 2) is not None  # ikkinchi adminga ham

            order = (await repo.list_user_orders(USER2, 0))[0][0]
            await env.click(ADMIN_ID, AdmSellCB(action="ok", order_id=order.id).pack(), message_text=photo_to_admin.caption, photo=True)
            assert f"#{order.id}</b> sonli arizangiz tasdiqlandi" in env.session.last(USER2)
            assert "128 000 so'm" in env.session.last(USER2)
            assert (await repo.get_user(USER2)).total_sell_uzs == 128_000
            assert await balance(USER) == 2560  # referal 2%
            # ikkinchi admin keyin bossa — hech narsa bo'lmaydi
            await env.click(2, AdmSellCB(action="no", order_id=order.id).pack(), photo=True)
            assert "allaqachon" in " ".join(env.session.alerts())
            assert (await repo.get_order(order.id)).status == "approved"

            # bekor qilish
            await env.click(USER2, ExchangeCB(action="sell", currency="TON").pack())
            await env.send(USER2, "1")
            await env.send(USER2, photo=True)
            await env.send(USER2, "8600123456789012")
            order2 = (await repo.list_user_orders(USER2, 0))[0][0]
            await env.click(ADMIN_ID, AdmSellCB(action="no", order_id=order2.id).pack(), photo=True)
            assert "bloklanishga sabab" in env.session.last(USER2)
            assert (await repo.get_order(order2.id)).status == "cancelled"
        finally:
            await env.close()
    run(scenario())


# =====================================================================
#  Tarix, qo'llanma, kurs, qo'llab-quvvatlash, menyu tozalash
# =====================================================================
def test_history_pagination_and_details():
    async def scenario():
        env = await make_env()
        try:
            await env.send(USER, "/start")
            await env.send(USER2, "/start")
            for _ in range(8):
                await repo.create_sell_order(USER, "TON", 1_000_000_000, 38400, 38400, HOT_WALLET, "f", "8600123412341234")
            other = await repo.create_sell_order(USER2, "TON", 1_000_000_000, 38400, 38400, HOT_WALLET, "f", "8600123412341234")

            await env.send(USER, texts.BTN_HISTORY)
            m = env.session.last_method("SendMessage", USER)
            assert m.text.count("#") == 6 and "1/2" in m.text
            await env.click(USER, HistoryCB(page=1).pack())
            edited = env.session.last_method("EditMessageText", USER)
            assert edited.text.count("#") == 2 and "2/2" in edited.text

            await env.click(USER, SimpleCB(action="hist_detail").pack())
            await env.send(USER, "#3")
            detail = env.session.last(USER)
            assert "Ariza #3" in detail and "Tekshirilmoqda" in detail and "**** ****" in detail and "f" != detail
            await env.click(USER, SimpleCB(action="hist_detail").pack())
            await env.send(USER, str(other.id))
            assert env.session.last(USER) == texts.HISTORY_NOT_FOUND
        finally:
            await env.close()
    run(scenario())


def test_guide_rates_support_and_menu_reset():
    async def scenario():
        env = await make_env()
        try:
            await env.settings.set("admin_username", "@admin_uz")
            await env.settings.set("news_channel", "@yangiliklar")
            await env.send(USER, "/start")
            await env.send(USER, texts.BTN_GUIDE)
            kb = env.session.last_method("SendMessage", USER).reply_markup.inline_keyboard
            assert sum(len(r) for r in kb) == 4
            await env.click(USER, GuideCB(topic="buy_usdt").pack())
            assert "USDT (TON) sotib olish" in env.session.last(USER)

            await env.send(USER, texts.BTN_RATES)
            rates = env.session.last(USER)
            assert "39 400 so'm" in rates and "99.9 TON" in rates and "500 USDT" in rates

            await env.send(USER, texts.BTN_SUPPORT)
            sup = env.session.last(USER)
            assert "@admin_uz" in sup and "@yangiliklar" in sup

            # jarayon o'rtasida menyu tugmasi -> holat tozalanadi
            await env.click(USER, ExchangeCB(action="sell", currency="TON").pack())
            await env.send(USER, texts.BTN_BALANCE)
            assert "Balans" in env.session.last(USER)
            await env.send(USER, "5")  # endi bu raqam sotish miqdori sifatida qabul qilinmaydi
            assert env.session.last(USER) == texts.UNKNOWN_INPUT

            # eskirgan tugma
            await env.click(USER, BuyConfirmCB(action="ok").pack())
            assert any("eskirgan" in a for a in env.session.alerts())
            # jarayon ichida stiker
            await env.click(USER, ExchangeCB(action="buy", currency="TON").pack())
            await env.send(USER, sticker=True)
            assert "Kutilgan ma'lumot" in env.session.last(USER)
        finally:
            await env.close()
    run(scenario())


# =====================================================================
#  Admin panel
# =====================================================================
def test_admin_stats_settings_prices_payment():
    async def scenario():
        env = await make_env()
        try:
            await env.send(ADMIN_ID, "/start")
            await env.send(USER, "/start")
            await env.send(ADMIN_ID, texts.BTN_A_STATS)
            stats = env.session.last(ADMIN_ID)
            assert "Foydalanuvchilar: <b>2</b>" in stats and "Sof foyda" in stats

            await env.send(ADMIN_ID, texts.BTN_A_SETTINGS)
            assert HOT_WALLET in env.session.last(ADMIN_ID)
            await env.click(ADMIN_ID, AdmSetCB(key="toggle_buy").pack())
            assert env.settings.buy_enabled is False
            await env.click(ADMIN_ID, AdmSetCB(key="toggle_buy").pack())
            assert env.settings.buy_enabled is True

            await env.click(ADMIN_ID, AdmSetCB(key="admin_username").pack())
            await env.send(ADMIN_ID, "@yangi_admin")
            assert env.settings.get("admin_username") == "@yangi_admin"

            await env.click(ADMIN_ID, AdmSetCB(key="sell_wallet_address").pack())
            await env.send(ADMIN_ID, "notanaddress")
            assert env.session.last(ADMIN_ID) == texts.INVALID_ADDRESS
            sell_wallet = new_address()
            await env.send(ADMIN_ID, sell_wallet)
            assert env.settings.get("sell_wallet_address") == sell_wallet

            # narxlar
            await env.send(ADMIN_ID, texts.BTN_A_PRICES)
            assert "Ustama: <b>1 000 so'm</b>" in env.session.last(ADMIN_ID)
            await env.click(ADMIN_ID, AdmSetCB(key="markup_uzs").pack())
            await env.send(ADMIN_ID, "2000")
            assert env.market.buy_price("TON") == 38400 + 2000
            assert env.market.buy_price("USDT") == 12800 + 2000
            assert env.market.sell_price("TON") == 38400
            await env.click(ADMIN_ID, AdmSetCB(key="buy_min_ton").pack())
            await env.send(ADMIN_ID, "0.5")
            assert env.settings.get("buy_min_ton") == "0.5"
            await env.click(ADMIN_ID, AdmSetCB(key="sell_range_usdt").pack())
            await env.send(ADMIN_ID, "100 5")
            assert "kichik" in env.session.last(ADMIN_ID)
            await env.send(ADMIN_ID, "5 2000")
            assert env.settings.get("sell_min_usdt") == "5" and env.settings.get("sell_max_usdt") == "2000"

            # to'lov tizimi
            old = env.settings.get("pay_secret_key")
            await env.send(ADMIN_ID, texts.BTN_A_PAYMENT)
            assert "https://domen.uz/pay" in env.session.last(ADMIN_ID)
            await env.click(ADMIN_ID, AdmSetCB(key="new_secret").pack())
            assert env.settings.get("pay_secret_key") != old and len(env.settings.get("pay_secret_key")) == 32
            await env.click(ADMIN_ID, AdmSetCB(key="show_url").pack())
            url_msg = env.session.last(ADMIN_ID)
            assert "miqdor=" in url_msg and env.settings.get("pay_secret_key") in url_msg
            await env.click(ADMIN_ID, AdmSetCB(key="card_number").pack())
            await env.send(ADMIN_ID, "1234")
            assert "16" in env.session.last(ADMIN_ID)
            await env.send(ADMIN_ID, "9860 1111 2222 3333")
            assert env.settings.get("card_number") == "9860111122223333"

            # referal sozlamasi
            await env.send(ADMIN_ID, texts.BTN_A_REFERRAL)
            assert "TOP-10" in env.session.last(ADMIN_ID)
            await env.click(ADMIN_ID, AdmSetCB(key="ref_percent").pack())
            await env.send(ADMIN_ID, "3.5")
            assert env.settings.ref_percent == 3.5

            # admin bo'lmagan foydalanuvchi admin tugmalarini bosa olmaydi
            await env.click(USER, AdmSetCB(key="toggle_buy").pack())
            assert env.settings.buy_enabled is True
        finally:
            await env.close()
    run(scenario())


def test_admin_user_management_and_block():
    async def scenario():
        env = await make_env()
        try:
            await env.settings.set("admin_username", "@admin_uz")
            await env.send(USER, "/start")
            await env.send(ADMIN_ID, texts.BTN_A_USERS)
            await env.send(ADMIN_ID, "777")
            assert "topilmadi" in env.session.last(ADMIN_ID)
            await env.send(ADMIN_ID, str(USER))
            card = env.session.last(ADMIN_ID)
            assert f"<code>{USER}</code>" in card and "Balans" in card

            await env.click(ADMIN_ID, AdmUserCB(action="add", user_id=USER).pack())
            await env.send(ADMIN_ID, "50 000")
            assert await balance(USER) == 50_000
            assert any("qo'shildi" in t for t in env.session.sent(USER))
            await env.click(ADMIN_ID, AdmUserCB(action="sub", user_id=USER).pack())
            await env.send(ADMIN_ID, "60000")
            assert "yetarli emas" in env.session.last(ADMIN_ID)
            await env.click(ADMIN_ID, AdmUserCB(action="sub", user_id=USER).pack())
            await env.send(ADMIN_ID, "10000")
            assert await balance(USER) == 40_000

            await env.click(ADMIN_ID, AdmUserCB(action="block", user_id=USER).pack())
            assert (await repo.get_user(USER)).is_blocked
            env.session.clear()
            await env.send(USER, texts.BTN_BALANCE)
            assert "bloklangansiz" in env.session.last(USER) and "@admin_uz" in env.session.last(USER)
            await env.click(USER, ExchangeCB(action="buy", currency="TON").pack())
            assert any("bloklangansiz" in a for a in env.session.alerts())

            await env.click(ADMIN_ID, AdmUserCB(action="unblock", user_id=USER).pack())
            await env.send(USER, texts.BTN_BALANCE)
            assert "40 000 so'm" in env.session.last(USER)
        finally:
            await env.close()
    run(scenario())


def test_broadcast_forward_and_blocked_users():
    async def scenario():
        env = await make_env()
        try:
            for uid in range(2000, 2030):
                await env.send(uid, "/start")
            env.session.blocked.update({2005, 2006})
            await env.send(ADMIN_ID, "/start")
            await env.send(ADMIN_ID, texts.BTN_A_BROADCAST)
            assert "31</b> ta faol" in env.session.last(ADMIN_ID)
            await env.send(ADMIN_ID, "Reklama matni!")
            await env.click(ADMIN_ID, AdmBroadcastCB(action="forward").pack())
            assert env.broadcaster.running
            for _ in range(200):
                if not env.broadcaster.running:
                    break
                await asyncio.sleep(0.05)
            forwards = [m for m in env.session.requests if type(m).__name__ == "ForwardMessage"]
            assert len(forwards) == 31  # 30 foydalanuvchi + admin
            assert env.broadcaster.stats["sent"] == 29 and env.broadcaster.stats["blocked"] == 2
            assert (await repo.get_user(2005)).is_active is False
            final = env.session.last(ADMIN_ID)
            assert "yuborib bo'lindi" in final and "Yuborildi: 29" in final
            # keyingi reklamada bloklaganlar o'tkazib yuboriladi
            assert len(await repo.all_broadcast_user_ids()) == 29
        finally:
            await env.close()
    run(scenario())


def test_channels_subscription_gate_and_referral_after_subscribe():
    async def scenario():
        env = await make_env()
        try:
            channel_id = -1009999
            env.session.chats["@mychannel"] = {"id": channel_id, "type": "channel", "title": "Mening kanalim", "username": "mychannel"}
            await env.send(ADMIN_ID, "/start")
            await env.send(USER, "/start")  # kanal qo'shilishidan oldin

            await env.send(ADMIN_ID, texts.BTN_A_CHANNELS)
            await env.click(ADMIN_ID, AdmChanCB(action="add").pack())
            await env.send(ADMIN_ID, "@mychannel")
            assert "admin emas" in env.session.last(ADMIN_ID)
            env.session.members[(channel_id, 999)] = "administrator"
            await env.send(ADMIN_ID, "@mychannel")
            assert "Kanal qo'shildi" in env.session.last(ADMIN_ID)
            assert len(env.channels.channels) == 1

            # obuna bo'lmagan foydalanuvchi — hech narsa ishlamaydi
            env.session.members[(channel_id, USER2)] = "left"
            await env.send(USER2, f"/start ref{USER}")
            assert "obuna bo'ling" in env.session.last(USER2)
            assert not any("yangi referal" in t for t in env.session.sent(USER))
            await env.send(USER2, texts.BTN_BALANCE)
            assert "obuna bo'ling" in env.session.last(USER2)
            await env.click(USER2, SimpleCB(action="check_sub").pack())
            assert texts.SUB_NOT_YET in env.session.alerts()

            # obuna bo'ldi -> referal hisoblanadi
            env.session.members[(channel_id, USER2)] = "member"
            await env.click(USER2, SimpleCB(action="check_sub").pack())
            assert texts.MAIN_MENU in env.session.sent(USER2)
            assert any("yangi referal" in t for t in env.session.sent(USER))
            assert await repo.count_referrals(USER) == 1

            # oldindan obuna bo'lgan foydalanuvchi — darhol qabul
            env.session.members[(channel_id, USER3)] = "member"
            await env.send(USER3, f"/start ref{USER}")
            assert "Assalomu alaykum" in env.session.last(USER3)
            assert await repo.count_referrals(USER) == 2

            # admin uchun obuna talab qilinmaydi
            env.session.members[(channel_id, ADMIN_ID)] = "left"
            await env.send(ADMIN_ID, texts.BTN_A_STATS)
            assert "Statistika" in env.session.last(ADMIN_ID)

            # ro'yxat va o'chirish
            await env.click(ADMIN_ID, AdmChanCB(action="list").pack())
            assert "@mychannel" in env.session.last(ADMIN_ID)
            ch = env.channels.channels[0]
            await env.click(ADMIN_ID, AdmChanCB(action="pick", channel_id=ch.id).pack())
            await env.click(ADMIN_ID, AdmChanCB(action="delete", channel_id=ch.id).pack())
            assert env.channels.channels == []
            env.session.members[(channel_id, USER2)] = "left"
            await env.send(USER2, texts.BTN_BALANCE)
            assert "Balans" in env.session.last(USER2)
        finally:
            await env.close()
    run(scenario())


def test_orders_recovery_on_restart_and_admin_recheck():
    async def scenario():
        env = await make_env()
        try:
            await env.send(USER, "/start")
            await give_balance(USER, 500_000)
            mk = lambda: repo.create_buy_order_and_charge(USER, "TON", 10**9, 39400, 38400, 39400, HOT_WALLET)  # noqa: E731
            a = await mk()                      # navbatda edi
            b = await mk()                      # yuborish boshlangan, lekin imzolanmagan
            c = await mk()                      # imzolangan va (ehtimol) yuborilgan
            await repo.start_sending(b.id)
            await repo.start_sending(c.id)
            await repo.save_order_message(c.id, "11" * 32, "22" * 32, 7, 1_900_000_000)

            requeue, recheck = await repo.recover_orders_on_startup()
            assert sorted(o.id for o in requeue) == [a.id, b.id]
            assert [o.id for o in recheck] == [c.id]

            env.ton.confirm_result = SendResult("unknown", "11" * 32, "tekshirib bo'lmadi")
            for o in requeue:
                await env.worker.enqueue(o)
            for o in recheck:
                await env.worker.enqueue_recheck(o)
            await env.drain()
            assert (await repo.get_order(a.id)).status == "done"
            assert (await repo.get_order(b.id)).status == "done"
            assert (await repo.get_order(c.id)).status == "unknown"
            assert env.ton.confirmed[0].seqno == 7 and env.ton.confirmed[0].valid_until == 1_900_000_000

            # muddat hali tugamagan — admin pulni qaytara olmaydi
            await env.click(ADMIN_ID, AdmOrderCB(action="refund", order_id=c.id).pack())
            assert any("muddati hali tugamagan" in a for a in env.session.alerts())
            assert (await repo.get_order(c.id)).status == "unknown"

            # admin qayta tekshiradi -> bajarildi
            env.ton.confirm_result = SendResult("done", "ef" * 32)
            await env.click(ADMIN_ID, AdmOrderCB(action="recheck", order_id=c.id).pack())
            await env.drain()
            done = await repo.get_order(c.id)
            assert done.status == "done" and done.tx_hash == "ef" * 32
            assert "bajarildi" in env.session.last(USER)
            assert await balance(USER) == 500_000 - 3 * 39400
        finally:
            await env.close()
    run(scenario())


def test_profit_and_stats_after_exchanges():
    async def scenario():
        env = await make_env()
        try:
            await env.send(USER, "/start")
            await give_balance(USER, 1_000_000)
            await env.click(USER, ExchangeCB(action="buy", currency="TON").pack())
            await env.send(USER, "2")
            await env.send(USER, new_address())
            await env.click(USER, BuyConfirmCB(action="ok").pack())
            await env.drain()
            st = await repo.orders_stats()
            assert st["done"] == 1 and st["sold_ton"] == 2 * 10**9 and st["sold_uzs"] == 78_800
            pr = await repo.profit_stats()
            assert pr["total"] == 2000
            async with session_scope() as s:
                assert (await s.execute(select(Order))).scalars().one().status == "done"
        finally:
            await env.close()
    run(scenario())


def test_buy_quote_valid_for_two_minutes(monkeypatch):
    import bot.handlers.exchange_buy as eb

    async def scenario():
        env = await make_env()
        try:
            await env.send(USER, "/start")
            await give_balance(USER, 500_000)

            async def set_ton_usd(value):
                async def fake(_s, force=False):
                    return value, 1.0, "test"
                env.market.fetch_crypto_usd = fake
                await env.market.refresh_all()

            # 1) kurs o'zgardi, lekin 2 daqiqa ichida tasdiqlandi — ko'rsatilgan narx saqlanadi
            await env.click(USER, ExchangeCB(action="buy", currency="TON").pack())
            await env.send(USER, "1")
            await env.send(USER, new_address())
            assert "2 daqiqa" in env.session.last(USER)
            await set_ton_usd(3.5)
            assert env.market.buy_price("TON") == 45_800
            await env.click(USER, BuyConfirmCB(action="ok").pack())
            await env.drain()
            first = (await repo.list_user_orders(USER, 0))[0][0]
            assert first.price == 39_400 and first.market_price == 38_400

            # 2) narx muddati o'tgan va kurs o'zgargan — qayta tasdiqlash so'raladi
            monkeypatch.setattr(eb, "QUOTE_TTL", -1)
            await env.click(USER, ExchangeCB(action="buy", currency="TON").pack())
            await env.send(USER, "1")
            await env.send(USER, new_address())
            await set_ton_usd(4.0)
            await env.click(USER, BuyConfirmCB(action="ok").pack())
            assert "Kurs yangilandi" in env.session.last(USER) and "52 200 so'm" in env.session.last(USER)
            await env.click(USER, BuyConfirmCB(action="ok").pack())
            await env.drain()
            second = (await repo.list_user_orders(USER, 0))[0][0]
            assert second.id != first.id and second.price == 52_200
            assert await balance(USER) == 500_000 - 39_400 - 52_200
        finally:
            await env.close()
    run(scenario())


def test_legacy_sending_orders_go_to_admin_and_graceful_stop():
    async def scenario():
        env = await make_env()
        try:
            await env.send(USER, "/start")
            await give_balance(USER, 500_000)
            legacy = await repo.create_buy_order_and_charge(USER, "TON", 10**9, 39400, 38400, 39400, HOT_WALLET)
            # eski versiya: 'sending', lekin belgi (send_started_at) va xabar ma'lumoti yo'q
            async with session_scope() as s:
                await s.execute(update(Order).where(Order.id == legacy.id).values(status="sending"))
            requeue, recheck = await repo.recover_orders_on_startup()
            assert requeue == [] and recheck == []
            assert (await repo.get_order(legacy.id)).status == "unknown"

            # graceful stop: joriy ish tugaydi, keyingisi boshlanmaydi
            started: list[int] = []
            release = asyncio.Event()
            original = env.ton.send_ton

            async def slow_send(destination, amount, comment="", on_signed=None):
                started.append(len(started) + 1)
                await release.wait()
                return await original(destination, amount, comment, on_signed=on_signed)

            env.ton.send_ton = slow_send
            a = await repo.create_buy_order_and_charge(USER, "TON", 10**9, 39400, 38400, 39400, HOT_WALLET)
            b = await repo.create_buy_order_and_charge(USER, "TON", 10**9, 39400, 38400, 39400, HOT_WALLET)
            await env.worker.enqueue(a)
            await env.worker.enqueue(b)
            await asyncio.sleep(0.1)
            assert started == [1]
            stop_task = asyncio.create_task(env.worker.stop(timeout=5))
            await asyncio.sleep(0.05)
            release.set()
            await stop_task
            assert started == [1], "keyingi ish boshlanmasligi kerak"
            assert (await repo.get_order(a.id)).status == "done"
            assert (await repo.get_order(b.id)).status == "processing"  # keyingi ishga tushishda davom etadi
            assert env.market.pending["TON"] == 0
        finally:
            await env.payments.stop()
            from bot.db.session import dispose_engine
            await dispose_engine()
    run(scenario())

"""Botni yig'ish va ishga tushirish (polling rejimi)."""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError, TelegramUnauthorizedError
from aiogram.fsm.storage.memory import MemoryStorage, SimpleEventIsolation
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault
from sqlalchemy.exc import SQLAlchemyError

from . import texts
from .config import Config, ConfigError, load_config
from .db import dispose_engine, init_db, repo, setup_engine
from .runtime import acquire_single_instance_lock, find_exposed_files
from .handlers import balance, exchange_buy, exchange_sell, fallback, info, menu
from .handlers import admin as admin_handlers
from .middlewares.access import AccessMiddleware
from .middlewares.menu_reset import MenuResetMiddleware
from .services.broadcast import BroadcastService
from .services.channels import ChannelService
from .services.exchange import TransferWorker
from .services.market import MarketService
from .services.notify import Notifier
from .services.payments import PaymentService
from .services.settings import SettingsService
from .services.ton import TonError, TonService
from .utils import esc, fmt_crypto, fmt_uzs
from .web.server import create_app, start_web

log = logging.getLogger("app")
BASE_DIR = Path(__file__).resolve().parent.parent


def setup_logging() -> None:
    (BASE_DIR / "data").mkdir(exist_ok=True)
    fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    # terminal yoki systemd (journalctl) — to'liq log; cron/fon rejimida konsolga faqat ogohlantirishlar
    # (to'liq log har doim data/bot.log da)
    verbose = sys.stdout.isatty() or bool(os.environ.get("JOURNAL_STREAM"))
    console.setLevel(logging.INFO if verbose else logging.WARNING)
    file_handler = RotatingFileHandler(BASE_DIR / "data" / "bot.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(fmt)
    root.handlers[:] = [console, file_handler]
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)


def build_dispatcher() -> Dispatcher:
    """Dispatcher: xotira FSM, har bir foydalanuvchi hodisalari navbat bilan (ikki marta bosish himoyasi)."""
    dp = Dispatcher(storage=MemoryStorage(), events_isolation=SimpleEventIsolation())
    access = AccessMiddleware()
    dp.message.outer_middleware(MenuResetMiddleware())
    dp.message.outer_middleware(access)
    dp.callback_query.outer_middleware(access)
    dp.include_routers(
        menu.router,
        admin_handlers.router,
        exchange_buy.router,
        exchange_sell.router,
        balance.router,
        info.router,
        fallback.router,
    )
    return dp


async def set_commands(bot: Bot, cfg: Config) -> None:
    user_cmds = [
        BotCommand(command="start", description="Botni ishga tushirish"),
        BotCommand(command="menu", description="Asosiy menyu"),
        BotCommand(command="id", description="Telegram ID raqamim"),
    ]
    admin_cmds = user_cmds + [
        BotCommand(command="admin", description="Admin panel"),
        BotCommand(command="unknown", description="Noaniq arizalar"),
    ]
    try:
        await bot.set_my_commands(user_cmds, scope=BotCommandScopeDefault())
    except TelegramAPIError as e:
        log.warning("Buyruqlar o'rnatilmadi: %s", e)
    for admin_id in cfg.admin_ids:
        try:
            await bot.set_my_commands(admin_cmds, scope=BotCommandScopeChat(chat_id=admin_id))
        except TelegramAPIError:
            pass  # admin hali botga /start bosmagan


def startup_report(cfg: Config, ton: TonService, market: MarketService, settings: SettingsService, web_ok: bool) -> str:
    lines = [
        "✅ <b>Bot ishga tushdi</b>",
        "",
        f"🏦 Hot wallet ({cfg.ton_wallet_version}, {cfg.ton_network}):",
        f"<code>{esc(ton.address)}</code>",
        f"💎 TON: {fmt_crypto(market.reserve['TON'], 'TON')} | 💰 USDT: {fmt_crypto(market.reserve['USDT'], 'USDT')}",
    ]
    if market.has_rates():
        lines.append(f"📊 TON: {fmt_uzs(market.market_price('TON'))} | USDT: {fmt_uzs(market.market_price('USDT'))}")
    else:
        lines.append("⚠️ Kurs hali yuklanmadi (internetni tekshiring)")
    if not cfg.web_enabled:
        lines.append(f"🔗 To'lov URL: <code>{esc(cfg.public_url)}/pay</code> (hosting PHP orqali — public/pay.php)")
    else:
        lines.append(f"🔗 To'lov URL: <code>{esc(cfg.public_url)}/pay</code>" + ("" if web_ok else " ⚠️ server ishga tushmadi!"))
    lines.append("🗄 Baza: MySQL" if cfg.database_url.startswith("mysql") else f"🗄 Baza: {esc(cfg.database_url.split(':', 1)[0])}")
    warnings = []
    if not cfg.toncenter_api_key:
        warnings.append("TONCENTER_API_KEY yo'q — bot sekin ishlaydi (1 so'rov/s). @toncenter botidan bepul kalit oling.")
    if not settings.get("card_number"):
        warnings.append("Karta raqami sozlanmagan — 💳 To'lov tizimi bo'limida kiriting.")
    if market.reserve_error:
        warnings.append(f"Zaxirani o'qib bo'lmadi: {esc(market.reserve_error)}")
    if warnings:
        lines.append("")
        lines.extend(f"⚠️ {w}" for w in warnings)
    return "\n".join(lines)


EXPOSURE_CHECK_INTERVAL = 6 * 3600


async def exposure_watch(cfg: Config, notifier: Notifier) -> None:
    """.env va bot kodi internetdan yuklab olinmasligini davriy tekshiradi."""
    while True:
        stats: dict = {}
        exposed = await find_exposed_files(cfg.public_url, stats=stats)
        if exposed:
            log.critical("DIQQAT! Maxfiy fayllar internetdan ochiq: %s", ", ".join(exposed))
            await notifier.admins(
                "⛔️ <b>XAVF! Maxfiy fayllar internetdan ochiq:</b>\n"
                + "\n".join(f"• {esc(cfg.public_url + p)}" for p in exposed)
                + "\n\n.env ichida hamyon kaliti (mnemonic) bor! Darhol yoping: domen papkasini (document root) "
                "<code>public</code> ga qarating yoki .htaccess / nginx sozlamasini qo'llang (README, 2- va 6-bo'lim). "
                "Kalit kimgadir ko'ringan bo'lishi mumkin bo'lsa — mablag'ni yangi hamyonga o'tkazing."
            )
        elif stats.get("reached"):
            log.info("Xavfsizlik tekshiruvi: .env va bot fayllari internetdan yopiq ✅ (%s)", cfg.public_url)
        elif not stats.get("skipped"):
            log.warning(
                "Xavfsizlik tekshiruvi: %s ga ulanib bo'lmadi — %s/.env ochilmasligini brauzerda o'zingiz tekshiring",
                cfg.public_url, cfg.public_url,
            )
        await asyncio.sleep(EXPOSURE_CHECK_INTERVAL)


async def main() -> None:
    setup_logging()
    try:
        cfg = load_config()
    except ConfigError as e:
        log.error("Sozlamada xato: %s", e)
        print(f"\n❌ .env sozlamasida xato: {e}\n")
        sys.exit(1)

    lock = acquire_single_instance_lock(BASE_DIR / "data" / "bot.lock")
    if lock is None:
        # cron har daqiqada ishga tushirsa ham ikkinchi nusxa ochilmaydi
        log.info("Bot allaqachon ishlab turibdi — ikkinchi nusxa ishga tushirilmadi")
        if sys.stdout.isatty():
            print("ℹ️ Bot allaqachon ishlab turibdi (data/bot.lock).")
        return

    setup_engine(cfg.database_url)
    log.info("Ma'lumotlar bazasi: %s", cfg.database_url_safe)
    bot = Bot(cfg.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    ton = TonService(cfg)
    market = payments = worker = broadcaster = None
    runner = None
    background: set[asyncio.Task] = set()
    try:
        try:
            await init_db()
        except (SQLAlchemyError, OSError) as e:
            log.error("Ma'lumotlar bazasiga ulanib bo'lmadi: %s", e)
            print(
                f"\n❌ MySQL ga ulanib bo'lmadi: {e}\n"
                "DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME ni tekshiring va baza yaratilganiga ishonch hosil qiling.\n"
            )
            sys.exit(1)
        settings = SettingsService()
        await settings.load()

        me = None
        for attempt in range(5):
            try:
                me = await bot.get_me()
                break
            except TelegramUnauthorizedError:
                print("\n❌ BOT_TOKEN noto'g'ri. @BotFather dan olingan tokenni .env ga yozing.\n")
                sys.exit(1)
            except TelegramAPIError as e:
                log.warning("Telegram'ga ulanib bo'lmadi (%s/5): %s", attempt + 1, e)
                await asyncio.sleep(5)
        if me is None:
            print("\n❌ Telegram serveriga ulanib bo'lmadi. Internet aloqasini tekshiring.\n")
            sys.exit(1)

        try:
            await ton.start()
        except TonError as e:
            print(f"\n❌ Hamyon xatosi: {e}\nTON_MNEMONIC va TON_WALLET_VERSION ni tekshiring (python check_wallet.py).\n")
            sys.exit(1)

        notifier = Notifier(bot, cfg, settings)
        channels = ChannelService(bot)
        await channels.reload()
        market = MarketService(cfg, settings, ton)
        payments = PaymentService(cfg, settings, notifier)
        worker = TransferWorker(cfg, settings, ton, market, notifier)
        broadcaster = BroadcastService(bot, cfg)

        async def notify_stock(currency: str) -> None:
            ids = await repo.pop_stock_alerts(currency)
            if not ids:
                return
            text = texts.stock_arrived(currency, market.max_buy_units(currency), market.buy_price(currency))
            for uid in ids:
                await notifier.user(uid, text)
                await asyncio.sleep(0.05)

        async def on_stock(currency: str) -> None:
            task = asyncio.create_task(notify_stock(currency))
            background.add(task)
            task.add_done_callback(background.discard)

        market.set_stock_callback(on_stock)
        market.set_alert_callback(notifier.admins)

        dp = build_dispatcher()
        dp.workflow_data.update(
            cfg=cfg,
            settings=settings,
            ton=ton,
            market=market,
            payments=payments,
            worker=worker,
            notifier=notifier,
            channels=channels,
            broadcaster=broadcaster,
            bot_username=me.username or "",
        )

        log.info("Bot: @%s | admin(lar): %s", me.username, ", ".join(map(str, cfg.admin_ids)))
        try:
            await asyncio.wait_for(market.refresh_all(), timeout=90)
        except asyncio.TimeoutError:
            log.warning("Boshlang'ich kurs/zaxira yangilanishi 90 soniyada tugamadi")

        requeue, recheck = await repo.recover_orders_on_startup()
        unknown = await repo.list_unknown_orders(100)

        market.start()
        payments.start()
        worker.start()
        for order in recheck:  # avval eski xabarlar natijasi (seqno to'qnashuvi bo'lmasin)
            await worker.enqueue_recheck(order)
        for order in requeue:
            await worker.enqueue(order)

        if cfg.web_enabled:
            try:
                runner = await start_web(create_app(payments, settings), cfg.web_host, cfg.web_port)
            except OSError as e:
                log.error("To'lov serveri ishga tushmadi (%s:%s): %s", cfg.web_host, cfg.web_port, e)

        await set_commands(bot, cfg)
        report = startup_report(cfg, ton, market, settings, runner is not None)
        if requeue or recheck:
            report += f"\n\n♻️ Qayta ishga tushish: {len(requeue)} ta ariza navbatga qo'yildi, {len(recheck)} ta ariza natijasi avtomatik tekshirilmoqda."
        if unknown:
            report += f"\n❓ Natijasi noaniq arizalar: {len(unknown)} ta — /unknown"
        await notifier.admins(report)
        watch = asyncio.create_task(exposure_watch(cfg, notifier), name="exposure-watch")
        background.add(watch)
        watch.add_done_callback(background.discard)

        await bot.delete_webhook(drop_pending_updates=False)
        log.info("Polling boshlandi")
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        log.info("Bot to'xtatilmoqda...")
        if broadcaster is not None:
            broadcaster.stop()
        if worker is not None:
            await worker.stop(timeout=60)  # joriy transferni tugatishga imkon beramiz
        for service in (market, payments):
            if service is not None:
                await service.stop()
        for task in list(background):
            task.cancel()
        if runner is not None:
            await runner.cleanup()
        await ton.stop()
        await bot.session.close()
        await dispose_engine()
        lock.close()
        log.info("Bot to'xtadi")

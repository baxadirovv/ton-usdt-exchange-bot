"""
Test muhiti: soxta Telegram API (barcha so'rovlarni yozib boradi), soxta TON xizmati,
xotiradagi baza va haqiqiy Dispatcher (barcha handler/middleware'lar bilan).
"""
from __future__ import annotations

import asyncio
import itertools
import json
import os
import time
from dataclasses import dataclass, field
from decimal import Decimal

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage, SimpleEventIsolation
from aiogram.types import Update
from ton_core import Address, ContractState, NetworkGlobalID, to_nano
from tonutils.clients import ToncenterClient
from tonutils.contracts import WalletV5R1

from bot.app import build_dispatcher
from bot.config import DEFAULT_USDT_MASTER, Config
from bot.db import init_db, setup_engine
from bot.db.session import dispose_engine, reset_db
from bot.services.broadcast import BroadcastService
from bot.services.channels import ChannelService
from bot.services.exchange import TransferWorker
from bot.services.market import MarketService
from bot.services.notify import Notifier
from bot.services.payments import PaymentService
from bot.services.settings import SettingsService
from bot.services.ton import AddressInfo, SendResult, SignedMessage

BOT_ID = 999
ADMIN_ID = 1

# MySQL bilan sinash:  TEST_DATABASE_URL="mysql+aiomysql://user:parol@127.0.0.1:3306/test_baza?charset=utf8mb4"
TEST_DB = os.getenv("TEST_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
IS_MYSQL = TEST_DB.startswith("mysql")


async def prepare_test_db() -> None:
    setup_engine(TEST_DB)
    if IS_MYSQL:
        await reset_db()
    else:
        await init_db()

_offline_client = ToncenterClient(network=NetworkGlobalID.MAINNET)


def new_address() -> str:
    w, _, _, _ = WalletV5R1.create(_offline_client)
    return w.address.to_str(is_bounceable=False)


HOT_WALLET = new_address()


# =====================================================================
#  Soxta Telegram sessiyasi
# =====================================================================
class FakeSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.requests: list = []
        self._ids = itertools.count(1000)
        self.blocked: set[int] = set()                         # botni bloklaganlar
        self.members: dict[tuple[int, int], str] = {}          # (chat_id, user_id) -> status
        self.chats: dict[str, dict] = {}                       # "@username" -> chat json

    async def close(self) -> None:  # noqa: D401
        return None

    async def stream_content(self, *args, **kwargs):  # pragma: no cover
        if False:
            yield b""

    def _msg(self, chat_id: int, text: str | None = None, caption: str | None = None) -> dict:
        d = {
            "message_id": next(self._ids),
            "date": int(time.time()),
            "chat": {"id": chat_id, "type": "private" if chat_id > 0 else "channel"},
            "from": {"id": BOT_ID, "is_bot": True, "first_name": "TestBot", "username": "test_bot"},
        }
        if text is not None:
            d["text"] = text
        if caption is not None:
            d["caption"] = caption
        return d

    def _user(self, uid: int) -> dict:
        return {"id": uid, "is_bot": uid == BOT_ID, "first_name": f"U{uid}"}

    def respond(self, method) -> tuple[int, dict]:
        name = type(method).__name__
        chat_id = getattr(method, "chat_id", None)
        if isinstance(chat_id, int) and chat_id in self.blocked and name in (
            "SendMessage", "SendPhoto", "SendDocument", "ForwardMessage", "CopyMessage"
        ):
            return 403, {"ok": False, "error_code": 403, "description": "Forbidden: bot was blocked by the user"}

        if name == "GetMe":
            return 200, {"ok": True, "result": {"id": BOT_ID, "is_bot": True, "first_name": "TestBot", "username": "test_bot"}}
        if name in ("SendMessage",):
            return 200, {"ok": True, "result": self._msg(chat_id, text=method.text)}
        if name in ("SendPhoto", "SendDocument"):
            return 200, {"ok": True, "result": self._msg(chat_id, caption=method.caption)}
        if name == "EditMessageText":
            return 200, {"ok": True, "result": self._msg(method.chat_id or 1, text=method.text)}
        if name == "EditMessageCaption":
            return 200, {"ok": True, "result": self._msg(method.chat_id or 1, caption=method.caption)}
        if name in ("EditMessageReplyMarkup", "AnswerCallbackQuery", "DeleteMessage", "SetMyCommands", "DeleteWebhook"):
            return 200, {"ok": True, "result": True}
        if name == "ForwardMessage":
            return 200, {"ok": True, "result": self._msg(chat_id, text="fwd")}
        if name == "CopyMessage":
            return 200, {"ok": True, "result": {"message_id": next(self._ids)}}
        if name == "GetChatMember":
            status = self.members.get((int(method.chat_id), int(method.user_id)), "member")
            user = self._user(int(method.user_id))
            if status == "administrator":
                result = {
                    "status": "administrator", "user": user, "can_be_edited": False, "is_anonymous": False,
                    "can_manage_chat": True, "can_delete_messages": True, "can_manage_video_chats": True,
                    "can_restrict_members": True, "can_promote_members": False, "can_change_info": True,
                    "can_invite_users": True, "can_post_stories": True, "can_edit_stories": True,
                    "can_delete_stories": True, "can_send_welcome_messages": True,
                }
            else:
                result = {"status": status, "user": user}
            return 200, {"ok": True, "result": result}
        if name == "GetChat":
            key = str(method.chat_id)
            chat = self.chats.get(key)
            if chat is None:
                return 400, {"ok": False, "error_code": 400, "description": "Bad Request: chat not found"}
            full = {"accent_color_id": 0, "max_reaction_count": 11, "accepted_gift_types": {
                "unlimited_gifts": False, "limited_gifts": False, "unique_gifts": False,
                "premium_subscription": False, "gifts_from_channels": False}}
            return 200, {"ok": True, "result": {**chat, **full}}
        raise AssertionError(f"Kutilmagan API metod: {name}")

    async def make_request(self, bot: Bot, method, timeout=None):
        if type(method).__name__ == "GetUpdates":
            await asyncio.sleep(0.05)
            return []
        self.requests.append(method)
        status, payload = self.respond(method)
        response = self.check_response(bot=bot, method=method, status_code=status, content=json.dumps(payload))
        return response.result

    # ---- qulay yordamchilar ----
    def sent(self, chat_id: int | None = None, kinds: tuple[str, ...] = ("SendMessage", "SendPhoto", "SendDocument", "EditMessageText", "EditMessageCaption")) -> list[str]:
        out = []
        for m in self.requests:
            if type(m).__name__ not in kinds:
                continue
            if chat_id is not None and getattr(m, "chat_id", None) != chat_id:
                continue
            out.append(getattr(m, "text", None) or getattr(m, "caption", None) or "")
        return out

    def last(self, chat_id: int) -> str:
        texts = self.sent(chat_id)
        return texts[-1] if texts else ""

    def last_method(self, name: str, chat_id: int | None = None):
        for m in reversed(self.requests):
            if type(m).__name__ == name and (chat_id is None or getattr(m, "chat_id", None) == chat_id):
                return m
        return None

    def alerts(self) -> list[str]:
        return [m.text or "" for m in self.requests if type(m).__name__ == "AnswerCallbackQuery" and m.text]

    def clear(self) -> None:
        self.requests.clear()


# =====================================================================
#  Soxta TON xizmati
# =====================================================================
class FakeTon:
    def __init__(self) -> None:
        self.address = HOT_WALLET
        self.ton_balance = to_nano(100)
        self.usdt_balance = 500 * 10**6
        self.sent: list[tuple] = []
        self.result: SendResult | None = None
        self.confirm_result: SendResult | None = None
        self.confirmed: list[SignedMessage] = []
        self.address_state = ContractState.ACTIVE
        self.seqno = 1

    async def get_ton_balance(self) -> int:
        return self.ton_balance

    async def get_usdt_balance(self) -> int:
        return self.usdt_balance

    async def get_address_info(self, address: Address) -> AddressInfo:
        return AddressInfo(address=address, state=self.address_state, balance=0)

    async def _sign(self, kind: str, on_signed) -> None:
        if on_signed is not None:
            msg = SignedMessage(
                norm_hash=f"{self.seqno:064x}", raw_hash=f"{self.seqno + 10**6:064x}",
                seqno=self.seqno, valid_until=int(time.time()) + 60, kind=kind,
            )
            await on_signed(msg)
        self.seqno += 1

    async def send_ton(self, destination, amount, comment="", on_signed=None):
        r = self.result or SendResult("done", "ab" * 32)
        if r.status != "failed" or r.tx_hash:
            await self._sign("ton", on_signed)
        self.sent.append(("TON", destination.to_str(is_bounceable=False), amount, comment))
        if r.status == "done":
            self.ton_balance -= amount
        return r

    async def send_usdt(self, destination, amount, comment="", query_id=0, on_signed=None):
        r = self.result or SendResult("done", "cd" * 32)
        if r.status != "failed" or r.tx_hash:
            await self._sign("usdt", on_signed)
        self.sent.append(("USDT", destination.to_str(is_bounceable=False), amount, comment, query_id))
        if r.status == "done":
            self.usdt_balance -= amount
        return r

    async def confirm(self, msg: SignedMessage) -> SendResult:
        self.confirmed.append(msg)
        return self.confirm_result or SendResult("done", "ef" * 32)

    async def chain_time(self) -> int:
        return int(time.time())

    def explorer_link(self, h: str) -> str:
        return f"https://tonviewer.com/transaction/{h}"

    def address_link(self, a: str) -> str:
        return f"https://tonviewer.com/{a}"


# =====================================================================
#  Muhit
# =====================================================================
DP = build_dispatcher()

TON_USD = 3.0
USD_UZS = 12800.0   # => TON real = 38 400 so'm, USDT real = 12 800 so'm


@dataclass
class Env:
    bot: Bot
    session: FakeSession
    ton: FakeTon
    cfg: Config
    settings: SettingsService
    market: MarketService
    payments: PaymentService
    worker: TransferWorker
    notifier: Notifier
    channels: ChannelService
    broadcaster: BroadcastService
    _ids: itertools.count = field(default_factory=lambda: itertools.count(1))
    names: dict = field(default_factory=dict)

    # ---- update yuborish ----
    def _user_json(self, uid: int, name: str | None = None, username: str | None = None) -> dict:
        if name:
            self.names[uid] = name
        d = {"id": uid, "is_bot": False, "first_name": self.names.get(uid, f"Foydalanuvchi{uid % 7}")}
        if username:
            d["username"] = username
        return d

    async def send(self, uid: int, text: str | None = None, photo: bool = False, name: str | None = None, document: dict | None = None, sticker: bool = False) -> None:
        n = next(self._ids)
        msg = {
            "message_id": n,
            "date": int(time.time()),
            "from": self._user_json(uid, name),
            "chat": {"id": uid, "type": "private", "first_name": self.names.get(uid, "x")},
        }
        if text is not None:
            msg["text"] = text
        if photo:
            msg["photo"] = [
                {"file_id": "PHOTO_SMALL", "file_unique_id": "s1", "width": 90, "height": 90},
                {"file_id": "PHOTO_BIG", "file_unique_id": "b1", "width": 900, "height": 900},
            ]
        if document is not None:
            msg["document"] = document
        if sticker:
            msg["sticker"] = {"file_id": "STK", "file_unique_id": "stk", "type": "regular", "width": 1, "height": 1, "is_animated": False, "is_video": False}
        upd = Update.model_validate({"update_id": n, "message": msg}, context={"bot": self.bot})
        await DP.feed_update(self.bot, upd)

    async def click(self, uid: int, data: str, message_text: str = "msg", photo: bool = False) -> None:
        n = next(self._ids)
        message = {
            "message_id": 50000 + n,
            "date": int(time.time()),
            "chat": {"id": uid, "type": "private"},
            "from": {"id": BOT_ID, "is_bot": True, "first_name": "TestBot"},
        }
        if photo:
            message["photo"] = [{"file_id": "PHOTO_BIG", "file_unique_id": "b1", "width": 900, "height": 900}]
            message["caption"] = message_text
        else:
            message["text"] = message_text
        cq = {"id": f"cb{n}", "from": self._user_json(uid), "chat_instance": "ci", "data": data, "message": message}
        upd = Update.model_validate({"update_id": n, "callback_query": cq}, context={"bot": self.bot})
        await DP.feed_update(self.bot, upd)

    async def drain(self) -> None:
        """Navbatdagi transferlar tugashini kutish."""
        await asyncio.wait_for(self.worker.queue.join(), timeout=10)

    async def close(self) -> None:
        await self.worker.stop()
        await self.payments.stop()
        await dispose_engine()


async def make_env(admin_ids: tuple[int, ...] = (ADMIN_ID,), broadcast_per_minute: int = 60000) -> Env:
    await prepare_test_db()
    settings = SettingsService()
    await settings.load()
    await settings.set("card_number", "8600123412341234")
    await settings.set("card_holder", "ALI VALIYEV")

    cfg = Config(
        bot_token="123456:TESTTOKEN",
        admin_ids=admin_ids,
        database_url=TEST_DB,
        ton_network="mainnet",
        ton_mnemonic="x " * 24,
        ton_wallet_version="v5r1",
        ton_mnemonic_type="auto",
        toncenter_api_key=None,
        usdt_jetton_master=DEFAULT_USDT_MASTER,
        web_host="127.0.0.1",
        web_port=0,
        public_url="https://domen.uz",
        rate_update_interval=60,
        payment_timeout_minutes=5,
        broadcast_per_minute=broadcast_per_minute,
        timezone="Asia/Tashkent",
    )
    session = FakeSession()
    bot = Bot(cfg.bot_token, session=session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    ton = FakeTon()
    notifier = Notifier(bot, cfg, settings)
    channels = ChannelService(bot)
    await channels.reload()
    market = MarketService(cfg, settings, ton)  # type: ignore[arg-type]

    async def fake_crypto(_s, force=False):
        return TON_USD, 1.0, "test"

    async def fake_uzs(_s):
        return USD_UZS, "test"

    market.fetch_crypto_usd = fake_crypto
    market.fetch_usd_uzs = fake_uzs
    await market.refresh_all()

    payments = PaymentService(cfg, settings, notifier)
    worker = TransferWorker(cfg, settings, ton, market, notifier)  # type: ignore[arg-type]
    worker.start()
    broadcaster = BroadcastService(bot, cfg)

    DP.fsm.storage = MemoryStorage()
    DP.fsm.events_isolation = SimpleEventIsolation()
    DP.workflow_data.clear()
    DP.workflow_data.update(
        cfg=cfg, settings=settings, ton=ton, market=market, payments=payments, worker=worker,
        notifier=notifier, channels=channels, broadcaster=broadcaster, bot_username="test_bot",
    )
    return Env(bot, session, ton, cfg, settings, market, payments, worker, notifier, channels, broadcaster)


def D(x: str) -> Decimal:
    return Decimal(x)

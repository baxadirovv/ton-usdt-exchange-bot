"""
TonService yuborish/tasdiqlash mantig'i testlari.
Haqiqiy tonutils hamyoni (imzolash, seqno, deploy) + soxta tarmoq + soxta TON Center v3 javoblari.
Asosiy qoida: pul faqat (a) muddat o'tib seqno o'zgarmaganda yoki (b) bizning tranzaksiyamiz topilib,
unda chiquvchi xabar yo'qligi aniq bo'lganda qaytariladi. Qolgan hamma noaniq holat — "unknown".
"""
from __future__ import annotations

import asyncio
import time

import pytest
from ton_core import (
    Address,
    Cell,
    ContractState,
    MessageAny,
    NetworkGlobalID,
    Slice,
    WalletV5Data,
    cell_to_b64,
    normalize_hash,
    to_nano,
)
from tonutils.clients import ToncenterClient
from tonutils.contracts import WalletV5R1
from tonutils.types import ContractInfo

from bot.config import DEFAULT_USDT_MASTER, Config
from bot.services import ton as ton_mod
from bot.services.ton import SignedMessage, TonService, VerifyUnavailable, b64, hash_to_bytes, parse_address, tx_ok, tx_status

MNEMONIC = None


@pytest.fixture(autouse=True)
def fast_timings(monkeypatch):
    monkeypatch.setattr(ton_mod, "MSG_TTL", 2)
    monkeypatch.setattr(ton_mod, "CONFIRM_MARGIN", 1)
    monkeypatch.setattr(ton_mod, "POLL_INTERVAL", 0.05)
    monkeypatch.setattr(ton_mod, "UNREACHABLE_GRACE", 1)
    monkeypatch.setattr(ton_mod, "VERIFY_RETRY_DELAY", 0.01)
    monkeypatch.setattr(ton_mod, "WALLET_VERIFY_SECONDS", 0.3)
    monkeypatch.setattr(ton_mod, "JETTON_VERIFY_SECONDS", 0.3)
    monkeypatch.setattr(ton_mod, "EXPIRED_VERIFY_SECONDS", 6)


def mnemonic() -> str:
    global MNEMONIC
    if MNEMONIC is None:
        _, _, _, words = WalletV5R1.create(ToncenterClient(network=NetworkGlobalID.MAINNET))
        MNEMONIC = " ".join(words)
    return MNEMONIC


def make_cfg(**over) -> Config:
    base = dict(
        bot_token="1:x", admin_ids=(1,), database_url="sqlite+aiosqlite:///:memory:", ton_network="mainnet",
        ton_mnemonic=mnemonic(), ton_wallet_version="v5r1", ton_mnemonic_type="auto", toncenter_api_key=None,
        usdt_jetton_master=DEFAULT_USDT_MASTER, web_host="127.0.0.1", web_port=0, public_url="https://x",
        rate_update_interval=60, payment_timeout_minutes=5, broadcast_per_minute=500, timezone="Asia/Tashkent",
    )
    base.update(over)
    return Config(**base)


class FakeChain:
    """Hamyon holati. send_message `accept=True` bo'lsa seqno ni oshiradi."""

    network = NetworkGlobalID.MAINNET

    def __init__(self, svc_ref, active=True, seqno=5, balance=to_nano(10), accept=True):
        self.svc_ref = svc_ref
        self.active = active
        self.seqno = seqno
        self.balance = balance
        self.accept = accept
        self.sent: list[str] = []
        self.foreign_bump = 0        # boshqa tranzaksiya seqno ni oshirsa
        self.read_errors = 0         # keyingi N ta o'qish xato beradi
        self.always_fail = False
        self.stale_seqno: int | None = None   # eskirgan backend: doim shu seqno ni ko'rsatadi
        self.accepted: list[bool] = []
        self.on_signed_seen: list[SignedMessage] = []

    async def get_info(self, address):
        if self.always_fail or self.read_errors > 0:
            self.read_errors = max(0, self.read_errors - 1)
            raise RuntimeError("HTTP 502 (soxta)")
        w = self.svc_ref["svc"].wallet
        if not self.active:
            return ContractInfo(balance=self.balance, state=ContractState.UNINIT)
        seqno = self.stale_seqno if self.stale_seqno is not None else self.seqno
        data = WalletV5Data(public_key=w.config.public_key, subwallet_id=w.config.subwallet_id, seqno=seqno).serialize()
        return ContractInfo(code_raw=cell_to_b64(w.state_init.code), data_raw=cell_to_b64(data), balance=self.balance, state=ContractState.ACTIVE)

    async def send_message(self, boc: str) -> None:
        assert self.on_signed_seen or not self.svc_ref.get("expect_signed"), "xabar saqlanmasdan yuborildi!"
        self.sent.append(boc)
        self.accepted.append(self.accept)
        if self.accept:
            self.active = True
            self.seqno += 1
        self.seqno += self.foreign_bump


class FakeV3:
    """Soxta TON Center v3. Bizning tranzaksiyamiz `index_ours` bo'lsa indekslangan hisoblanadi."""

    def __init__(self, chain: FakeChain, svc: TonService):
        self.chain, self.svc = chain, svc
        self.calls: list[tuple[str, dict]] = []
        self.available = True
        self.index_ours = True
        self.ours_ok = True
        self.ours_out = 1
        self.foreign: list[dict] = []     # begona tranzaksiyalar (eng yangisi birinchi)
        self.ours_position = 0            # bizniki ro'yxatda qaysi o'rinda
        self.by_hash_supported = True
        self.jetton_tx: dict | None = {"hash": b64(b"\x55" * 32), "description": {"aborted": False, "compute_ph": {"success": True}}, "out_msgs": [{}]}
        self.chain_offset = 0          # blokcheyn (indekser) vaqti - mahalliy vaqt
        self.chain_times: list[int] = []

    def our_tx(self) -> dict | None:
        if not (self.index_ours and self.chain.sent and self.chain.accepted and self.chain.accepted[-1]):
            return None
        boc = self.chain.sent[-1]
        raw = Cell.one_from_boc(boc).hash
        return {
            "account": self.svc.address_raw.upper(),
            "hash": b64(b"\x42" * 32),
            "in_msg": {"hash": b64(raw), "hash_norm": b64(bytes.fromhex(normalize_hash(boc)))},
            "out_msgs": [{"hash": b64(bytes([0x22]) * 32)} for _ in range(self.ours_out)],
            "description": {"aborted": not self.ours_ok, "compute_ph": {"success": True}, "action": {"success": self.ours_ok}},
        }

    def wallet_list(self) -> list[dict]:
        txs = list(self.foreign)
        ours = self.our_tx()
        if ours is not None:
            txs.insert(min(self.ours_position, len(txs)), ours)
        return txs

    async def __call__(self, path: str, params: dict) -> dict:
        self.calls.append((path, dict(params)))
        if not self.available:
            raise VerifyUnavailable("down")
        if path == "/transactionsByMessage":
            if params["msg_hash"] == b64(bytes([0x22]) * 32):
                return {"transactions": [self.jetton_tx] if self.jetton_tx else []}
            ours = self.our_tx()
            if self.by_hash_supported and ours is not None and params["msg_hash"] in (ours["in_msg"]["hash"],):
                return {"transactions": [ours]}
            return {"transactions": []}
        if path == "/transactions":
            txs = self.wallet_list()
            off, lim = params["offset"], params["limit"]
            return {"transactions": txs[off:off + lim]}
        if path == "/masterchainInfo":
            now = int(time.time()) + self.chain_offset
            self.chain_times.append(now)
            return {"first": {}, "last": {"seqno": 1, "gen_utime": str(now)}}
        raise AssertionError(path)


def foreign_tx(i: int) -> dict:
    return {
        "hash": b64(i.to_bytes(32, "big")),
        "in_msg": {"hash": b64((10**6 + i).to_bytes(32, "big")), "hash_norm": None},
        "out_msgs": [],
        "description": {"aborted": False, "compute_ph": {"success": True}, "action": {"success": True}},
    }


def build(**chain_kwargs) -> tuple[TonService, FakeChain, FakeV3]:
    svc = TonService(make_cfg())
    ref = {"svc": svc}
    chain = FakeChain(ref, **chain_kwargs)
    svc.client = chain  # type: ignore[assignment]
    svc.open_wallet(chain)
    svc._http = object()  # type: ignore[assignment]
    v3 = FakeV3(chain, svc)
    svc._v3 = v3  # type: ignore[assignment]
    return svc, chain, v3


def run(coro):
    return asyncio.run(coro)


def body_seqno_and_valid_until(boc: str) -> tuple[int, int]:
    msg = MessageAny.deserialize(Slice.one_from_boc(boc))
    cs = msg.body.begin_parse()
    cs.skip_bits(32 + 32)      # op, subwallet_id   (W5: imzo oxirida)
    valid_until = cs.load_uint(32)
    seqno = cs.load_uint(32)
    return seqno, valid_until


# ---------------------------------------------------------------------
def test_helpers_and_address_validation():
    raw = bytes(range(32))
    assert hash_to_bytes(raw.hex()) == raw and hash_to_bytes(b64(raw)) == raw
    assert hash_to_bytes("xyz") is None and hash_to_bytes(None) is None
    assert tx_ok({"description": {"aborted": False, "compute_ph": {"success": True}, "action": {"success": True}}, "out_msgs": [{}]})[0]
    assert not tx_ok({"description": {"aborted": True}})[0]
    assert not tx_ok({"description": {}, "out_msgs": []})[0]
    assert not tx_ok({})[0]
    for bad in ("=", "salom", "", "0:ab", "1000:" + "a" * 64, "-1:" + "a" * 64, "UQ" + "A" * 46):
        assert parse_address(bad) is None, bad
    good = parse_address("0:" + "ab" * 32)
    assert good is not None and good.wc == 0


def test_send_ton_done_found_by_hash():
    async def scenario():
        svc, chain, v3 = build()
        r = await svc.send_ton(Address(svc.address), to_nano(1), "Order #1")
        assert r.status == "done", r
        assert r.tx_hash == (b"\x42" * 32).hex()
        assert chain.seqno == 6
        assert MessageAny.deserialize(Slice.one_from_boc(chain.sent[0])).init is None
        assert v3.calls[0][0] == "/transactionsByMessage"
    run(scenario())


def test_message_saved_before_sending_and_save_failure_blocks_send():
    async def scenario():
        svc, chain, v3 = build()
        svc_ref = chain.svc_ref
        svc_ref["expect_signed"] = True

        async def on_signed(msg: SignedMessage):
            chain.on_signed_seen.append(msg)

        r = await svc.send_ton(Address(svc.address), to_nano(1), on_signed=on_signed)
        assert r.status == "done"
        saved = chain.on_signed_seen[0]
        seqno, valid_until = body_seqno_and_valid_until(chain.sent[0])
        assert saved.seqno == seqno == 5 and saved.valid_until == valid_until
        assert saved.norm_hash == normalize_hash(chain.sent[0])

        svc2, chain2, _ = build()

        async def broken(msg):
            raise RuntimeError("disk full")

        r2 = await svc2.send_ton(Address(svc2.address), to_nano(1), on_signed=broken)
        assert r2.status == "failed" and chain2.sent == []
    run(scenario())


def test_insufficient_balance_and_seqno_read_error_do_not_send():
    async def scenario():
        svc, chain, _ = build(balance=to_nano("0.5"))
        r = await svc.send_ton(Address(svc.address), to_nano(1))
        assert r.status == "failed" and chain.sent == []

        # seqno ni o'qishda xato — jimgina 0 ishlatilmaydi, umuman yuborilmaydi
        svc2, chain2, _ = build(seqno=7)
        balance_reads = {"n": 0}
        orig = chain2.get_info

        async def flaky(address):
            balance_reads["n"] += 1
            if balance_reads["n"] == 2:  # 1-o'qish: balans, 2-o'qish: seqno
                raise RuntimeError("HTTP 502")
            return await orig(address)

        chain2.get_info = flaky  # type: ignore[assignment]
        r2 = await svc2.send_ton(Address(svc2.address), to_nano(1))
        assert r2.status == "failed" and chain2.sent == []
    run(scenario())


def test_expired_refund_needs_chain_time_and_definitive_lookup():
    async def scenario():
        # oddiy holat: xabar tarmoqqa kirmadi -> blokcheyn vaqti o'tgach, topilmadi -> qaytariladi
        svc, chain, v3 = build(accept=False)
        r = await svc.send_ton(Address(svc.address), to_nano(1))
        assert r.status == "failed" and "muddati" in r.reason
        msg_valid_until = body_seqno_and_valid_until(chain.sent[0])[1]
        assert max(v3.chain_times) > msg_valid_until + ton_mod.CONFIRM_MARGIN

        # TON Center ishlamasa — muddat o'tgan bo'lsa ham pul QAYTARILMAYDI
        svc2, chain2, v3b = build(accept=False)
        v3b.available = False
        r2 = await svc2.send_ton(Address(svc2.address), to_nano(1))
        assert r2.status == "unknown"
    run(scenario())


def test_stale_seqno_backend_does_not_cause_refund():
    async def scenario():
        # xabar bajarilgan va indekslangan, lekin v2 backend eski seqno ni ko'rsatmoqda
        svc, chain, v3 = build(seqno=5)
        chain.stale_seqno = 5
        r = await svc.send_ton(Address(svc.address), to_nano(1))
        assert r.status == "done", r
    run(scenario())


def test_fast_server_clock_waits_for_chain_time():
    async def scenario():
        svc, chain, v3 = build(accept=False)
        v3.chain_offset = -3  # server soati blokcheyndan 3 soniya oldinda
        r = await svc.send_ton(Address(svc.address), to_nano(1))
        assert r.status == "failed"
        valid_until = body_seqno_and_valid_until(chain.sent[0])[1]
        # qaror faqat blokcheyn vaqti muddat+zaxiradan o'tgandan keyin qabul qilingan
        assert v3.chain_times[-1] > valid_until + ton_mod.CONFIRM_MARGIN
        assert any(t <= valid_until + ton_mod.CONFIRM_MARGIN for t in v3.chain_times)
    run(scenario())


def test_tx_status_is_tri_state():
    full_ok = {"description": {"aborted": False, "compute_ph": {"success": True}, "action": {"success": True}}, "out_msgs": [{}]}
    assert tx_status(full_ok)[0] == "ok"
    assert tx_status({"out_msgs": [{}]})[0] == "unclear"                                   # description yo'q
    assert tx_status({"description": {"aborted": False, "compute_ph": {"success": True}}})[0] == "unclear"  # out_msgs yo'q
    assert tx_status({"description": {"compute_ph": {"success": True}}, "out_msgs": [{}]})[0] == "unclear"  # aborted yo'q
    assert tx_status({"description": {"aborted": True}, "out_msgs": [{}]})[0] == "failed"
    assert tx_status({"description": {"aborted": False, "compute_ph": {"success": True}}, "out_msgs": []})[0] == "failed"


def test_spammed_wallet_never_refunds_and_paging_finds_our_tx():
    async def scenario():
        # bizning tx hash bo'yicha topilmaydi, ro'yxatda 150 ta begona tranzaksiya — 2-sahifada bizniki
        svc, chain, v3 = build()
        v3.by_hash_supported = False
        v3.foreign = [foreign_tx(i) for i in range(150)]
        v3.ours_position = 120
        r = await svc.send_ton(Address(svc.address), to_nano(1))
        assert r.status == "done", r
        pages = [c for c in v3.calls if c[0] == "/transactions"]
        assert any(p[1]["offset"] == 100 for p in pages)

        # hujum: seqno o'sdi (begona tx), biznikini umuman topib bo'lmaydi -> HECH QACHON "failed" emas
        svc2, chain2, v3b = build(accept=False)
        chain2.foreign_bump = 1
        v3b.index_ours = False
        v3b.foreign = [foreign_tx(i) for i in range(150)]
        r2 = await svc2.send_ton(Address(svc2.address), to_nano(1))
        assert r2.status == "unknown", r2
    run(scenario())


def test_v3_unavailable_after_seqno_advance_is_unknown():
    async def scenario():
        svc, chain, v3 = build()
        v3.available = False
        r = await svc.send_ton(Address(svc.address), to_nano(1))
        assert r.status == "unknown"
    run(scenario())


def test_action_phase_failure_is_definitive_refund():
    async def scenario():
        svc, chain, v3 = build()
        v3.ours_ok, v3.ours_out = False, 0
        r = await svc.send_ton(Address(svc.address), to_nano(1))
        assert r.status == "failed"
    run(scenario())


def test_unreachable_after_send_is_unknown():
    async def scenario():
        svc, chain, v3 = build()
        orig_send = chain.send_message

        async def send_then_break(boc):
            await orig_send(boc)
            chain.always_fail = True

        chain.send_message = send_then_break  # type: ignore[assignment]
        r = await svc.send_ton(Address(svc.address), to_nano(1))
        assert r.status == "unknown" and "o'qib bo'lmadi" in r.reason
    run(scenario())


def test_uninit_wallet_deploys_with_explicit_expiry():
    async def scenario():
        svc, chain, v3 = build(active=False, seqno=0)
        r = await svc.send_ton(Address(svc.address), to_nano(1))
        assert r.status == "done", r
        msg = MessageAny.deserialize(Slice.one_from_boc(chain.sent[0]))
        assert msg.init is not None
        seqno, valid_until = body_seqno_and_valid_until(chain.sent[0])
        assert seqno == 0 and valid_until < 2**32 - 1 and abs(valid_until - time.time()) < 30
    run(scenario())


def test_seqno_floor_and_stale_view_is_unknown():
    async def scenario():
        svc, chain, v3 = build(seqno=10)
        await svc.send_ton(Address(svc.address), to_nano(1))
        assert svc._seqno_floor == 11
        chain.seqno = 10          # eskirgan (lag) ma'lumot
        chain.accept = False
        r = await svc.send_ton(Address(svc.address), to_nano(1))
        assert body_seqno_and_valid_until(chain.sent[-1])[0] == 11  # 10 emas
        assert r.status == "unknown"   # tarmoq ko'rinishi biznikidan past — avtomatik qaytarilmaydi
    run(scenario())


def test_send_usdt_jetton_verification(monkeypatch):
    captured = {}
    real_builder = ton_mod.JettonTransferBuilder

    def spy(*args, **kwargs):
        captured.update(kwargs)
        return real_builder(*args, **kwargs)

    monkeypatch.setattr(ton_mod, "JettonTransferBuilder", spy)

    async def scenario():
        for jetton_tx, expected in (
            ({"hash": b64(b"\x55" * 32), "description": {"aborted": False, "compute_ph": {"success": True}}, "out_msgs": [{}]}, "done"),
            ({"hash": b64(b"\x56" * 32), "description": {"aborted": True, "compute_ph": {"success": False}}, "out_msgs": [{}]}, "unknown"),
            (None, "unknown"),
        ):
            svc, chain, v3 = build()
            v3.jetton_tx = jetton_tx

            async def usdt_balance():
                return 100 * 10**6

            async def jetton_wallet():
                return Address(svc.address)

            svc.get_usdt_balance = usdt_balance  # type: ignore[assignment]
            svc.usdt_jetton_wallet = jetton_wallet  # type: ignore[assignment]
            r = await svc.send_usdt(Address(svc.address), 5 * 10**6, "Order #2", query_id=2)
            assert r.status == expected, (jetton_tx, r)
        assert captured["bounce"] is True and captured["query_id"] == 2

        svc, chain, _ = build()

        async def low():
            return 1

        async def jw2():
            return Address(svc.address)

        svc.get_usdt_balance = low  # type: ignore[assignment]
        svc.usdt_jetton_wallet = jw2  # type: ignore[assignment]
        r = await svc.send_usdt(Address(svc.address), 5 * 10**6)
        assert r.status == "failed" and chain.sent == []
    run(scenario())


def test_confirm_existing_message_after_restart():
    async def scenario():
        svc, chain, v3 = build(seqno=5)
        r = await svc.send_ton(Address(svc.address), to_nano(1))
        assert r.status == "done"
        boc = chain.sent[0]
        seqno, valid_until = body_seqno_and_valid_until(boc)
        msg = SignedMessage(normalize_hash(boc), Cell.one_from_boc(boc).hash.hex(), seqno, valid_until, "ton")
        svc2, chain2, v3b = build(seqno=6)   # "qayta ishga tushgan" bot
        chain2.sent, chain2.accepted = [boc], [True]
        r2 = await svc2.confirm(msg)
        assert r2.status == "done"
        # imzolangan, lekin hech qachon kirmagan xabar -> muddatdan keyin failed
        svc3, chain3, v3c = build(seqno=5)
        r3 = await svc3.confirm(SignedMessage("aa" * 32, "bb" * 32, 5, int(time.time()) + 1, "ton"))
        assert r3.status == "failed"
    run(scenario())


def test_mnemonic_12_and_24_words_and_tg_wallet():
    from ton_core import multichain_mnemonic_new
    from tonutils.contracts import WalletTg

    client = ToncenterClient(network=NetworkGlobalID.MAINNET)
    words12 = multichain_mnemonic_new()
    for version, cls in (("v5r1", WalletV5R1), ("tg", WalletTg)):
        svc = TonService(make_cfg(ton_mnemonic=" ".join(words12), ton_wallet_version=version))
        svc.open_wallet(client)
        expected, _, _, _ = cls.from_mnemonic(client, words12)
        assert svc.address == expected.address.to_str(is_bounceable=False)
    svc24 = TonService(make_cfg())
    svc24.open_wallet(client)
    expected24, _, _, _ = WalletV5R1.from_mnemonic(client, mnemonic())
    assert svc24.address == expected24.address.to_str(is_bounceable=False)

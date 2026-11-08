"""
TON blokcheyn bilan ishlash (tonutils + TON Center API):
  - hot wallet (W5 / V4R2 / Telegram Gram Wallet) ni mnemonic dan ochish (12 yoki 24 so'z)
  - TON va USDT (jetton) balanslarini o'qish
  - TON va USDT ni avtomatik yuborish va NATIJANI ISHONCHLI TASDIQLASH

Xavfsiz yuborish qoidalari:
  1. Seqno har doim xatoni yashirmaydigan so'rov bilan o'qiladi (o'qilmasa — hech narsa yuborilmaydi).
  2. Har bir xabar aniq seqno va 60 soniyalik muddat (valid_until) bilan imzolanadi.
     Xabar ma'lumotlari (hash, seqno, muddat) YUBORISHDAN OLDIN bazaga yoziladi.
  3. Pul FAQAT ikki holatda avtomatik qaytariladi:
       a) BLOKCHEYN vaqti (TON Center indeksatori) muddatdan o'tib ketgan va shu vaqtgacha
          indekslangan tranzaksiyalar orasida bizning xabar yo'q — xabar bajarilmagan va endi bajarila olmaydi
          (server soati yoki eskirgan seqno ga ishonilmaydi);
       b) bizning tranzaksiyamiz topildi va unda hech qanday chiquvchi xabar yo'qligi aniq.
  4. Seqno o'sgan bo'lsa — tranzaksiya xabar hash'i bo'yicha topilib, tekshiriladi.
     Topilmasa yoki tekshirib bo'lmasa — "noaniq" (admin qaror qiladi), hech qachon avtomatik qaytarilmaydi.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import time
from dataclasses import dataclass
from typing import Awaitable, Callable

import aiohttp
from ton_core import Address, ContractState, MnemonicType, NetworkGlobalID, to_nano
from tonutils.clients import ToncenterClient
from tonutils.contracts import (
    JettonTransferBuilder,
    TONTransferBuilder,
    WalletTg,
    WalletV4R2,
    WalletV5R1,
    get_wallet_address_get_method,
    get_wallet_data_get_method,
)
from tonutils.types import DEFAULT_HTTP_RETRY_POLICY

from ..config import Config

log = logging.getLogger("ton")

WALLET_CLASSES = {"v5r1": WalletV5R1, "v4r2": WalletV4R2, "tg": WalletTg}
MNEMONIC_TYPES = {"ton": MnemonicType.TON, "multichain": MnemonicType.MULTICHAIN}

JETTON_GAS_NANO = to_nano("0.05")        # USDT yuborishda biriktiriladigan TON (gas)
TON_FEE_RESERVE_NANO = to_nano("0.01")   # TON yuborishda komissiya zaxirasi
MIN_GAS_RESERVE_NANO = to_nano("0.1")    # hot walletda doim qoladigan TON (USDT gas uchun)

MSG_TTL = 60                  # xabar amal qilish muddati (soniya)
CONFIRM_MARGIN = 30           # muddatdan keyin qo'shimcha kutish (soniya)
POLL_INTERVAL = 2.5           # seqno tekshirish oralig'i (soniya)
UNREACHABLE_GRACE = 120       # muddatdan keyin ham seqno o'qilmasa, shuncha kutib "noaniq"
VERIFY_RETRY_DELAY = 3.0      # tranzaksiyani qayta qidirish oralig'i (soniya)
WALLET_VERIFY_SECONDS = 90    # hamyon tranzaksiyasini qidirish vaqti
JETTON_VERIFY_SECONDS = 90    # jetton-wallet tranzaksiyasini qidirish vaqti
EXPIRED_VERIFY_SECONDS = 300  # "muddati o'tdi" ni blokcheyn vaqti bo'yicha tasdiqlash uchun kutish
TX_PAGE_SIZE = 100
TX_MAX_PAGES = 10


class TonError(Exception):
    """Hamyonni ochishdagi xato."""


class VerifyUnavailable(Exception):
    """TON Center v3 orqali tekshirib bo'lmadi."""


@dataclass
class SendResult:
    status: str          # done | failed | unknown
    tx_hash: str = ""    # tranzaksiya hash (hex) yoki xabar hash
    reason: str = ""


@dataclass
class SignedMessage:
    """Imzolangan (yuborilgan yoki yuborilayotgan) xabar haqida — bazaga saqlanadi."""
    norm_hash: str       # normallashtirilgan hash (hex)
    raw_hash: str        # xabar cell hash (hex)
    seqno: int
    valid_until: int
    kind: str            # ton | usdt


@dataclass
class AddressInfo:
    address: Address
    state: ContractState
    balance: int

    @property
    def is_active(self) -> bool:
        return self.state == ContractState.ACTIVE


def parse_address(text: str) -> Address | None:
    """Foydalanuvchi manzilini tekshiradi: format, checksum, workchain 0, 32 baytli hash."""
    try:
        addr = Address((text or "").strip())
        if addr.wc != 0 or len(addr.hash_part) != 32:
            return None
        addr.to_str(is_bounceable=False)
        return addr
    except Exception:  # noqa: BLE001 — har qanday noto'g'ri kiritish
        return None


def hash_to_bytes(value: object) -> bytes | None:
    """hex (64 belgi) yoki base64/base64url hashni baytlarga aylantiradi."""
    if value is None:
        return None
    v = str(value).strip()
    if not v:
        return None
    if len(v) == 64:
        try:
            return bytes.fromhex(v)
        except ValueError:
            pass
    try:
        padded = v + "=" * (-len(v) % 4)
        if "-" in v or "_" in v:
            raw = base64.urlsafe_b64decode(padded)
        else:
            raw = base64.b64decode(padded)
        return raw if len(raw) == 32 else None
    except (ValueError, TypeError):
        return None


def b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


def tx_status(tx: dict) -> tuple[str, str]:
    """TON Center v3 tranzaksiyasi: ('ok' | 'failed' | 'unclear', sabab).
    'failed' faqat aniq belgilar bo'lganda; ma'lumot to'liq bo'lmasa — 'unclear' (pul qaytarilmaydi)."""
    d = tx.get("description")
    if not isinstance(d, dict):
        return "unclear", "description yo'q"
    if d.get("aborted") is True:
        return "failed", "aborted"
    compute = d.get("compute_ph")
    if isinstance(compute, dict) and compute.get("success") is False:
        return "failed", "compute phase failed"
    action = d.get("action")
    if isinstance(action, dict) and action.get("success") is False:
        return "failed", "action phase failed"
    out = tx.get("out_msgs")
    if not isinstance(out, list):
        return "unclear", "out_msgs yo'q"
    if len(out) == 0:
        return "failed", "chiquvchi xabar yo'q"
    if d.get("aborted") is not False or not isinstance(compute, dict) or compute.get("success") is not True:
        return "unclear", "tranzaksiya holati to'liq emas"
    return "ok", ""


def tx_ok(tx: dict) -> tuple[bool, str]:
    status, why = tx_status(tx)
    return status == "ok", why


class TonService:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.client: ToncenterClient | None = None
        self.wallet = None
        self.address: str = ""        # user-friendly (UQ...)
        self.address_raw: str = ""    # 0:abcd...
        self._usdt_wallet: Address | None = None
        self._lock = asyncio.Lock()
        self._seqno_floor = 0
        self._http: aiohttp.ClientSession | None = None
        base = "https://testnet.toncenter.com" if cfg.is_testnet else "https://toncenter.com"
        self._v3_base = f"{base}/api/v3"
        self._v3_lock = asyncio.Lock()
        self._v3_last = 0.0
        self.ready = False

    # ------------------------------------------------------------------
    #  Ishga tushirish
    # ------------------------------------------------------------------
    def open_wallet(self, client) -> None:
        wallet_cls = WALLET_CLASSES[self.cfg.ton_wallet_version]
        mnemonic_type = MNEMONIC_TYPES.get(self.cfg.ton_mnemonic_type)
        try:
            self.wallet, _, _, _ = wallet_cls.from_mnemonic(client, self.cfg.ton_mnemonic, mnemonic_type=mnemonic_type)
        except Exception as e:  # noqa: BLE001
            raise TonError(f"Mnemonic noto'g'ri yoki wallet versiyasiga mos emas: {e}") from e
        self.address = self.wallet.address.to_str(is_bounceable=False)
        self.address_raw = self.wallet.address.to_str(is_user_friendly=False)

    async def start(self) -> None:
        network = NetworkGlobalID.TESTNET if self.cfg.is_testnet else NetworkGlobalID.MAINNET
        self.client = ToncenterClient(
            network=network,
            api_key=self.cfg.toncenter_api_key,
            rps_limit=7 if self.cfg.toncenter_api_key else 1,
            retry_policy=DEFAULT_HTTP_RETRY_POLICY,
            timeout=15.0,
        )
        await self.client.connect()
        self.open_wallet(self.client)
        self._http = aiohttp.ClientSession()
        self.ready = True
        log.info("Hot wallet (%s, %s): %s", self.cfg.ton_wallet_version, self.cfg.ton_network, self.address)

    async def stop(self) -> None:
        if self._http is not None:
            await self._http.close()
            self._http = None
        if self.client is not None:
            try:
                await self.client.close()
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------
    #  Balanslar
    # ------------------------------------------------------------------
    async def get_ton_balance(self) -> int:
        """Hot wallet TON balansi (nanoton)."""
        info = await self.client.get_info(self.wallet.address)
        return int(info.balance)

    async def usdt_jetton_wallet(self) -> Address:
        """Bizning USDT jetton-wallet manzilimiz (bir marta hisoblanadi)."""
        if self._usdt_wallet is None:
            self._usdt_wallet = await get_wallet_address_get_method(
                client=self.client,
                address=Address(self.cfg.usdt_jetton_master),
                owner_address=self.wallet.address,
            )
        return self._usdt_wallet

    async def get_usdt_balance(self) -> int:
        """Hot wallet USDT balansi (mikro-USDT, 10^6). Jetton wallet hali yo'q bo'lsa 0."""
        jw = await self.usdt_jetton_wallet()
        info = await self.client.get_info(jw)
        if info.state != ContractState.ACTIVE:
            return 0
        data = await get_wallet_data_get_method(self.client, jw)
        return int(data[0])

    async def get_address_info(self, address: Address) -> AddressInfo:
        info = await self.client.get_info(address)
        return AddressInfo(address=address, state=info.state, balance=int(info.balance))

    # ------------------------------------------------------------------
    #  Yuborish (ochiq API)
    # ------------------------------------------------------------------
    async def send_ton(
        self,
        destination: Address,
        amount_nano: int,
        comment: str = "",
        on_signed: Callable[[SignedMessage], Awaitable[None]] | None = None,
    ) -> SendResult:
        async with self._lock:
            try:
                balance = await self.get_ton_balance()
            except Exception as e:  # noqa: BLE001
                return SendResult("failed", reason=f"balansni o'qib bo'lmadi: {e}")
            if balance < amount_nano + TON_FEE_RESERVE_NANO:
                return SendResult("failed", reason="Hot walletda TON yetarli emas (komissiya bilan).")
            builder = TONTransferBuilder(
                destination=destination,
                amount=amount_nano,
                body=comment or None,
                bounce=False,  # faollashmagan hamyonga ham yetib boradi
            )
            return await self._send_and_confirm(builder, "ton", on_signed)

    async def send_usdt(
        self,
        destination: Address,
        amount_units: int,
        comment: str = "",
        query_id: int = 0,
        on_signed: Callable[[SignedMessage], Awaitable[None]] | None = None,
    ) -> SendResult:
        async with self._lock:
            try:
                ton_balance = await self.get_ton_balance()
                usdt_balance = await self.get_usdt_balance()
                jw = await self.usdt_jetton_wallet()
            except Exception as e:  # noqa: BLE001
                return SendResult("failed", reason=f"balansni o'qib bo'lmadi: {e}")
            if ton_balance < JETTON_GAS_NANO + TON_FEE_RESERVE_NANO:
                return SendResult("failed", reason="Hot walletda gas uchun TON yetarli emas (kamida 0.06 TON).")
            if usdt_balance < amount_units:
                return SendResult("failed", reason="Hot walletda USDT yetarli emas.")
            builder = JettonTransferBuilder(
                destination=destination,
                jetton_amount=amount_units,
                jetton_wallet_address=jw,
                response_address=self.wallet.address,
                forward_payload=comment or None,
                forward_amount=1,
                amount=JETTON_GAS_NANO,
                query_id=query_id,
                bounce=True,  # jetton-wallet xato bersa, gas TON qaytib keladi
            )
            return await self._send_and_confirm(builder, "usdt", on_signed)

    async def confirm(self, msg: SignedMessage) -> SendResult:
        """Avval imzolangan xabar natijasini aniqlash (masalan, bot qayta ishga tushgach)."""
        async with self._lock:
            return await self._confirm(msg)

    # ------------------------------------------------------------------
    #  Ichki: seqno
    # ------------------------------------------------------------------
    async def _read_seqno_strict(self) -> int:
        """Seqno ni o'qiydi. Xato bo'lsa — istisno (hech qachon jimgina 0 qaytarmaydi)."""
        info = await self.client.get_info(self.wallet.address)
        if info.state == ContractState.ACTIVE:
            if not info.data_raw:
                raise RuntimeError("faol hamyon ma'lumoti (data) bo'sh keldi")
            # hamyon klassining o'z tahlilchisi (W5 uchun tarmoq ID si ham hisobga olinadi)
            self.wallet._info = info
            return int(self.wallet.state_data.seqno)
        if info.state in (ContractState.UNINIT, ContractState.NONEXIST):
            return 0
        raise RuntimeError(f"hamyon holati: {info.state}")

    async def _wait_outcome(self, msg: SignedMessage) -> str:
        """'advanced' — seqno biznikidan oshdi; 'expired' — muddat o'tdi va seqno hamon biznikiga teng;
        'unreachable' — seqno ni o'qib bo'lmadi."""
        deadline = msg.valid_until + CONFIRM_MARGIN
        expired_reads = 0
        while True:
            try:
                current = await self._read_seqno_strict()
            except Exception as e:  # noqa: BLE001
                log.debug("seqno o'qilmadi: %s", e)
                if time.time() > deadline + UNREACHABLE_GRACE:
                    return "unreachable"
            else:
                if current > msg.seqno:
                    return "advanced"
                if current == msg.seqno and time.time() > deadline:
                    expired_reads += 1
                    if expired_reads >= 2:  # ketma-ket ikki marta tasdiqlansin
                        return "expired"
                elif current < msg.seqno and time.time() > deadline + UNREACHABLE_GRACE:
                    # tarmoq ma'lumoti eskirgan ko'rinadi — xavfsiz qaror qilib bo'lmaydi
                    return "unreachable"
            await asyncio.sleep(POLL_INTERVAL)

    # ------------------------------------------------------------------
    #  Ichki: yuborish va tasdiqlash
    # ------------------------------------------------------------------
    async def _send_and_confirm(
        self,
        builder,
        kind: str,
        on_signed: Callable[[SignedMessage], Awaitable[None]] | None,
    ) -> SendResult:
        # 1) seqno (xatoni yashirmaydigan o'qish) va imzolash
        try:
            seqno = max(await self._read_seqno_strict(), self._seqno_floor)
            valid_until = int(time.time()) + MSG_TTL
            params = self.wallet._params_model(seqno=seqno, valid_until=valid_until)
            ext = await self.wallet.build_external_message([builder], params)
            msg = SignedMessage(
                norm_hash=str(ext.normalized_hash),
                raw_hash=ext.to_cell().hash.hex(),
                seqno=seqno,
                valid_until=valid_until,
                kind=kind,
            )
        except Exception as e:  # noqa: BLE001 — hech narsa yuborilmagan
            log.exception("Xabarni tayyorlab bo'lmadi: %s", e)
            return SendResult("failed", reason=f"xabarni tayyorlab bo'lmadi: {e}")

        # 2) xabar ma'lumotini YUBORISHDAN OLDIN saqlash (bot to'xtasa ham tekshirib bo'ladi)
        if on_signed is not None:
            try:
                await on_signed(msg)
            except Exception as e:  # noqa: BLE001 — saqlanmadi, demak yubormaymiz
                log.exception("Xabar ma'lumotini saqlab bo'lmadi: %s", e)
                return SendResult("failed", reason=f"bazaga yozib bo'lmadi: {e}")

        # 3) tarmoqqa yuborish (xato bo'lsa ham xabar yetib borgan bo'lishi mumkin — natijani kutamiz)
        try:
            await self.client.send_message(ext.as_hex)
        except Exception as e:  # noqa: BLE001
            log.warning("send_message xatosi (xabar baribir yetib borgan bo'lishi mumkin): %s", e)

        return await self._confirm(msg)

    async def _confirm(self, msg: SignedMessage) -> SendResult:
        outcome = await self._wait_outcome(msg)
        if outcome == "unreachable":
            return SendResult("unknown", msg.norm_hash, "hamyon holatini o'qib bo'lmadi")
        if outcome == "expired":
            return await self._confirm_expired(msg)

        # Seqno o'sdi — bizning tranzaksiyamizni topamiz
        self._seqno_floor = max(self._seqno_floor, msg.seqno + 1)
        tx, last_error = None, ""
        deadline = time.time() + WALLET_VERIFY_SECONDS
        while True:
            try:
                tx = await self._find_wallet_tx(msg)
            except VerifyUnavailable as e:
                last_error = str(e)
            if tx is not None or time.time() > deadline:
                break
            await asyncio.sleep(VERIFY_RETRY_DELAY)

        if tx is None:
            reason = "seqno o'sdi, lekin tranzaksiya topilmadi"
            if last_error:
                reason += f" (TON Center: {last_error})"
            return SendResult("unknown", msg.norm_hash, reason)
        return await self._evaluate(tx, msg)

    async def _confirm_expired(self, msg: SignedMessage) -> SendResult:
        """Seqno o'zgarmagan ko'rinadi. Pulni qaytarishdan oldin BLOKCHEYN vaqti muddatdan o'tganini va
        shu vaqtgacha indekslangan tranzaksiyalar orasida bizning xabar yo'qligini tasdiqlaymiz."""
        last_error = ""
        deadline = time.time() + EXPIRED_VERIFY_SECONDS
        while True:
            try:
                chain_now = await self.chain_time()  # qidiruvdan OLDIN o'qiladi
                if chain_now > msg.valid_until + CONFIRM_MARGIN:
                    tx = await self._find_wallet_tx(msg)
                    if tx is not None:
                        return await self._evaluate(tx, msg)
                    return SendResult("failed", msg.norm_hash, "xabar muddati o'tdi va tarmoqqa kirmadi")
                last_error = "blokcheyn vaqti hali xabar muddatidan o'tmadi"
            except VerifyUnavailable as e:
                last_error = str(e)
            if time.time() > deadline:
                return SendResult("unknown", msg.norm_hash, f"muddat tugaganini tasdiqlab bo'lmadi: {last_error}")
            await asyncio.sleep(VERIFY_RETRY_DELAY)

    async def _evaluate(self, tx: dict, msg: SignedMessage) -> SendResult:
        tx_bytes = hash_to_bytes(tx.get("hash"))
        tx_hash = tx_bytes.hex() if tx_bytes else msg.norm_hash
        status, why = tx_status(tx)
        if status == "failed":
            # Bizning tranzaksiyamiz topildi va unda hech narsa yuborilmagani aniq
            return SendResult("failed", tx_hash, f"hamyon tranzaksiyasi muvaffaqiyatsiz: {why}")
        if status != "ok":
            return SendResult("unknown", tx_hash, f"tranzaksiya holati noaniq: {why}")
        if msg.kind == "usdt":
            return await self._confirm_jetton(tx, tx_hash)
        return SendResult("done", tx_hash)

    async def _confirm_jetton(self, wallet_tx: dict, tx_hash: str) -> SendResult:
        out_hash = None
        for m in wallet_tx.get("out_msgs") or []:
            if isinstance(m, dict) and m.get("hash"):
                out_hash = str(m["hash"])
                break
        if not out_hash:
            return SendResult("unknown", tx_hash, "jetton xabari topilmadi")
        last_error = ""
        deadline = time.time() + JETTON_VERIFY_SECONDS
        while True:
            try:
                jtx = await self._find_tx_by_in_msg(out_hash)
            except VerifyUnavailable as e:
                jtx, last_error = None, str(e)
            if jtx is not None:
                status, why = tx_status(jtx)
                if status == "ok":
                    return SendResult("done", tx_hash)
                return SendResult("unknown", tx_hash, f"jetton-wallet tranzaksiyasi muvaffaqiyatsiz yoki noaniq: {why}")
            if time.time() > deadline:
                return SendResult("unknown", tx_hash, f"jetton tranzaksiyasi tasdiqlanmadi {last_error}".strip())
            await asyncio.sleep(VERIFY_RETRY_DELAY)

    # ------------------------------------------------------------------
    #  TON Center v3
    # ------------------------------------------------------------------
    async def _v3(self, path: str, params: dict) -> dict:
        if self._http is None:
            raise VerifyUnavailable("HTTP sessiya yo'q")
        headers = {"Accept": "application/json"}
        if self.cfg.toncenter_api_key:
            headers["X-API-Key"] = self.cfg.toncenter_api_key
        min_gap = 0.15 if self.cfg.toncenter_api_key else 1.1
        last_error: object = None
        for attempt in range(4):
            async with self._v3_lock:
                gap = time.monotonic() - self._v3_last
                if gap < min_gap:
                    await asyncio.sleep(min_gap - gap)
                self._v3_last = time.monotonic()
            try:
                async with self._http.get(
                    f"{self._v3_base}{path}",
                    params=params,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status == 429 or resp.status >= 500:
                        last_error = f"HTTP {resp.status}"
                        await asyncio.sleep(1.5 * (attempt + 1))
                        continue
                    if resp.status != 200:
                        raise VerifyUnavailable(f"HTTP {resp.status}")
                    data = await resp.json(content_type=None)
                    if not isinstance(data, dict):
                        raise VerifyUnavailable("JSON noto'g'ri")
                    return data
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
                last_error = e
                await asyncio.sleep(1.5 * (attempt + 1))
        raise VerifyUnavailable(str(last_error))

    def _is_our_tx(self, tx: dict) -> bool:
        account = tx.get("account")
        if not account:
            return True
        try:
            return Address(str(account)) == self.wallet.address
        except Exception:  # noqa: BLE001
            return False

    async def _find_wallet_tx(self, msg: SignedMessage) -> dict | None:
        """Bizning tashqi xabarimiz bajarilgan hamyon tranzaksiyasini topadi.
        1) xabar hash'i bo'yicha to'g'ridan-to'g'ri qidiruv; 2) yuborilgan vaqtdan beri barcha
        tranzaksiyalarni sahifalab ko'rib chiqish (begona tranzaksiyalar ko'p bo'lsa ham topiladi)."""
        targets = {hash_to_bytes(msg.norm_hash), hash_to_bytes(msg.raw_hash)} - {None}
        for h in (msg.raw_hash, msg.norm_hash):
            raw = hash_to_bytes(h)
            if raw is None:
                continue
            data = await self._v3("/transactionsByMessage", {"msg_hash": b64(raw), "direction": "in", "limit": 10, "offset": 0})
            txs = data.get("transactions")
            if not isinstance(txs, list):
                raise VerifyUnavailable("'transactions' maydoni yo'q")
            for tx in txs:
                if isinstance(tx, dict) and self._is_our_tx(tx):
                    return tx

        since = msg.valid_until - MSG_TTL - 120
        for page in range(TX_MAX_PAGES):
            data = await self._v3(
                "/transactions",
                {"account": self.address_raw, "start_utime": since, "limit": TX_PAGE_SIZE, "offset": page * TX_PAGE_SIZE, "sort": "desc"},
            )
            txs = data.get("transactions")
            if not isinstance(txs, list):
                raise VerifyUnavailable("'transactions' maydoni yo'q")
            for tx in txs:
                if not isinstance(tx, dict):
                    continue
                in_msg = tx.get("in_msg") or {}
                for key in ("hash_norm", "hash"):
                    if hash_to_bytes(in_msg.get(key)) in targets:
                        return tx
            if len(txs) < TX_PAGE_SIZE:
                return None
        raise VerifyUnavailable("tranzaksiyalar juda ko'p — to'liq ko'rib chiqilmadi")

    async def chain_time(self) -> int:
        """TON Center indeksatori yetib kelgan oxirgi masterchain blok vaqti (unix)."""
        data = await self._v3("/masterchainInfo", {})
        last = data.get("last") or {}
        try:
            return int(last.get("gen_utime"))
        except (TypeError, ValueError) as e:
            raise VerifyUnavailable("masterchainInfo: gen_utime yo'q") from e

    async def _find_tx_by_in_msg(self, msg_hash: str) -> dict | None:
        data = await self._v3("/transactionsByMessage", {"msg_hash": msg_hash, "direction": "in", "limit": 5, "offset": 0})
        txs = data.get("transactions")
        if not isinstance(txs, list):
            raise VerifyUnavailable("'transactions' maydoni yo'q")
        return txs[0] if txs and isinstance(txs[0], dict) else None

    # ------------------------------------------------------------------
    def explorer_link(self, tx_hash: str) -> str:
        base = "https://testnet.tonviewer.com" if self.cfg.is_testnet else "https://tonviewer.com"
        return f"{base}/transaction/{tx_hash}"

    def address_link(self, address: str) -> str:
        base = "https://testnet.tonviewer.com" if self.cfg.is_testnet else "https://tonviewer.com"
        return f"{base}/{address}"

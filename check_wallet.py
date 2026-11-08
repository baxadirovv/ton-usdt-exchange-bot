"""
Hamyonni tekshirish vositasi.

.env dagi TON_MNEMONIC (12 yoki 24 so'z) dan qaysi manzil chiqishini ko'rsatadi.
Chiqqan manzil hamyon ilovangizdagi (Tonkeeper / Telegram Wallet) manzil bilan BIR XIL bo'lishi shart!

    python check_wallet.py

Mnemonic ekranga chiqarilmaydi.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from ton_core import (
    Address,
    ContractState,
    MnemonicType,
    NetworkGlobalID,
    multichain_mnemonic_is_valid,
    to_amount,
    ton_mnemonic_is_valid,
)
from tonutils.clients import ToncenterClient
from tonutils.contracts import WalletTg, WalletV4R2, WalletV5R1, get_wallet_address_get_method, get_wallet_data_get_method

BASE = Path(__file__).resolve().parent
DEFAULT_USDT_MASTER = "EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs"
VERSIONS = {"v5r1": ("W5 (v5r1)", WalletV5R1), "v4r2": ("v4r2", WalletV4R2), "tg": ("Telegram Gram Wallet", WalletTg)}


def main() -> None:
    load_dotenv(BASE / ".env", interpolate=False)
    words = " ".join((os.getenv("TON_MNEMONIC") or "").replace('"', "").replace("'", "").split()).lower().split()
    network = (os.getenv("TON_NETWORK") or "mainnet").strip().lower()
    chosen = (os.getenv("TON_WALLET_VERSION") or "v5r1").strip().lower()
    chosen = {"w5": "v5r1", "v5": "v5r1", "v4": "v4r2"}.get(chosen, chosen)
    api_key = (os.getenv("TONCENTER_API_KEY") or "").strip() or None
    usdt_master = (os.getenv("USDT_JETTON_MASTER") or DEFAULT_USDT_MASTER).strip()

    if len(words) not in (12, 24):
        sys.exit(f"❌ TON_MNEMONIC 12 yoki 24 so'zdan iborat bo'lishi kerak (hozir: {len(words)} ta).")

    ton_ok = ton_mnemonic_is_valid(words)
    multi_ok = multichain_mnemonic_is_valid(words)
    print(f"\n🔑 Mnemonic: {len(words)} ta so'z")
    print(f"   • TON standarti (Tonkeeper 24 so'z): {'✅ mos' if ton_ok else '— mos emas'}")
    print(f"   • BIP-39 / multichain (12 so'z, Telegram Gram Wallet): {'✅ mos' if multi_ok else '— mos emas'}")
    if not ton_ok and not multi_ok:
        sys.exit("❌ Mnemonic hech bir standartga mos emas — so'zlarda xato bor.")

    net = NetworkGlobalID.TESTNET if network == "testnet" else NetworkGlobalID.MAINNET
    client = ToncenterClient(network=net, api_key=api_key, rps_limit=1 if not api_key else 5)

    types = []
    if ton_ok:
        types.append(("ton", MnemonicType.TON))
    if multi_ok:
        types.append(("multichain", MnemonicType.MULTICHAIN))

    print(f"\n🌐 Tarmoq: {network}")
    print("📍 Shu mnemonicdan chiqadigan manzillar:\n")
    chosen_address = None
    for type_name, mtype in types:
        for key, (title, cls) in VERSIONS.items():
            if key == "tg" and mtype == MnemonicType.TON:
                print(f"   {title:<24} [{type_name}]: — (faqat 12 so'zli Telegram mnemonic uchun)")
                continue
            try:
                wallet, _, _, _ = cls.from_mnemonic(client, words, mnemonic_type=mtype)
            except Exception as e:  # noqa: BLE001
                print(f"   {title:<24} [{type_name}]: — ({str(e)[:60]})")
                continue
            addr = wallet.address.to_str(is_bounceable=False)
            mark = "  ⬅️ .env da tanlangan" if key == chosen else ""
            print(f"   {title:<24} [{type_name}]: {addr}{mark}")
            if key == chosen and chosen_address is None:
                chosen_address = addr

    print(
        "\n👉 Hamyon ilovangizdagi manzilni yuqoridagilar bilan solishtiring.\n"
        "   Mos kelgan qatordagi versiyani TON_WALLET_VERSION ga yozing (v5r1 / v4r2 / tg).\n"
        "   Agar [ton] va [multichain] ikkalasi chiqsa va mos kelgani [multichain] bo'lsa:\n"
        "   TON_MNEMONIC_TYPE=multichain deb yozing.\n"
    )

    if chosen_address:
        try:
            asyncio.run(show_balance(client, chosen_address, usdt_master))
        except Exception as e:  # noqa: BLE001
            print(f"⚠️ Balansni o'qib bo'lmadi (internet yoki API): {e}")


async def show_balance(client: ToncenterClient, address: str, usdt_master: str) -> None:
    await client.connect()
    try:
        info = await client.get_info(Address(address))
        state = {
            ContractState.ACTIVE: "faol (active)",
            ContractState.UNINIT: "hali deploy qilinmagan (uninit) — birinchi yuborishda avtomatik deploy bo'ladi",
            ContractState.NONEXIST: "tarmoqda yo'q (hali pul kelmagan)",
            ContractState.FROZEN: "muzlatilgan (frozen)",
        }.get(info.state, str(info.state))
        print(f"🏦 Tanlangan hamyon: {address}")
        print(f"   Holati: {state}")
        print(f"   💎 TON: {to_amount(int(info.balance), precision=4)}")
        jw = await get_wallet_address_get_method(client=client, address=Address(usdt_master), owner_address=Address(address))
        jinfo = await client.get_info(jw)
        usdt = 0
        if jinfo.state == ContractState.ACTIVE:
            data = await get_wallet_data_get_method(client, jw)
            usdt = int(data[0])
        print(f"   💰 USDT: {to_amount(usdt, decimals=6, precision=2)}\n")
    finally:
        await client.close()


if __name__ == "__main__":
    main()

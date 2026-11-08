"""Ishga tushirish yordamchilari: yagona nusxa qulfi va maxfiy fayllar ochiq emasligini tekshirish."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import IO

import aiohttp

log = logging.getLogger("runtime")


def acquire_single_instance_lock(lock_path: Path) -> IO | None:
    """Bitta papkadan faqat BITTA bot ishlashini ta'minlaydi.
    Qulf olinsa — fayl obyekti (jarayon tugaguncha saqlang), boshqa bot ishlayotgan bo'lsa — None."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(lock_path, "a+")  # noqa: SIM115 — jarayon davomida ochiq turishi kerak
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    handle.seek(0)
    handle.truncate()
    handle.write(str(os.getpid()))
    handle.flush()
    return handle


# Internetdan ochiq bo'lmasligi shart bo'lgan fayllar va ulardagi belgilar
SENSITIVE_PROBES = (
    ("/.env", ("TON_MNEMONIC", "BOT_TOKEN", "DB_PASSWORD")),
    ("/bot/config.py", ("load_config",)),
    ("/main.py", ("bot.app",)),
    ("/data/bot.log", ("| INFO", "| WARNING")),
)


async def find_exposed_files(
    public_url: str, timeout: float = 10.0, allow_local: bool = False, stats: dict | None = None
) -> list[str]:
    """PUBLIC_URL orqali maxfiy fayllar yuklab olinadimi — tekshiradi. Ochiq fayllar ro'yxatini qaytaradi.
    `stats` berilsa: stats["reached"] — server javob bergan tekshiruvlar soni, stats["skipped"] — tekshirilmadi."""
    stats = stats if stats is not None else {}
    stats.update(reached=0, skipped=False)
    base = (public_url or "").rstrip("/")
    if not base.startswith(("http://", "https://")) or (
        not allow_local and ("localhost" in base or "127.0.0.1" in base)
    ):
        stats["skipped"] = True
        return []
    exposed: list[str] = []
    client_timeout = aiohttp.ClientTimeout(total=timeout)
    try:
        async with aiohttp.ClientSession(timeout=client_timeout) as session:
            for path, markers in SENSITIVE_PROBES:
                try:
                    # http -> https kabi yo'naltirishlarga ergashamiz (aks holda ochiq fayl ko'rinmay qolishi mumkin)
                    async with session.get(base + path, allow_redirects=True, max_redirects=3) as resp:
                        stats["reached"] += 1
                        if resp.status != 200:
                            continue
                        body = (await resp.content.read(65536)).decode("utf-8", "ignore")
                        if any(marker in body for marker in markers):
                            exposed.append(path)
                except (aiohttp.ClientError, TimeoutError, OSError) as e:
                    log.debug("Tekshiruv %s: %s", path, e)
    except Exception as e:  # noqa: BLE001
        log.debug("Ochiqlik tekshiruvi ishlamadi: %s", e)
    return exposed

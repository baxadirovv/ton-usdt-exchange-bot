"""
Reklama (ommaviy xabar) yuborish.

- Daqiqasiga N ta (standart 500) — aniq tezlikda (har bir yuborish o'z vaqt oralig'ida)
- Bir vaqtda bir nechta yuborish (sekin javoblar tezlikni pasaytirmaydi)
- Telegram "flood" cheklovida avtomatik kutadi va davom etadi
- Har 5 soniyada hisobot yangilanadi, istalgan payt to'xtatish mumkin
- Bot boshqa foydalanuvchilarga javob berishda davom etadi (fon vazifasi)
"""
from __future__ import annotations

import asyncio
import logging
import time

from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNotFound,
    TelegramRetryAfter,
)
from aiogram.types import InlineKeyboardMarkup

from ..config import Config
from ..db import repo

log = logging.getLogger("broadcast")

MAX_CONCURRENCY = 10
REPORT_EVERY = 5.0  # soniya


class BroadcastService:
    def __init__(self, bot: Bot, cfg: Config) -> None:
        self.bot = bot
        self.cfg = cfg
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._pause_until = 0.0
        self.stats = {"total": 0, "sent": 0, "blocked": 0, "failed": 0}

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def stop(self) -> bool:
        if not self.running:
            return False
        self._stop.set()
        return True

    async def start(
        self,
        admin_chat_id: int,
        from_chat_id: int,
        message_id: int,
        mode: str,
        stop_markup: InlineKeyboardMarkup | None = None,
    ) -> bool:
        """mode: 'forward' | 'copy'. Boshqa reklama ketayotgan bo'lsa False."""
        if self.running:
            return False
        self._stop = asyncio.Event()
        self._task = asyncio.create_task(
            self._run(admin_chat_id, from_chat_id, message_id, mode, stop_markup), name="broadcast"
        )
        return True

    # ------------------------------------------------------------------
    async def _send_one(self, user_id: int, from_chat_id: int, message_id: int, mode: str) -> None:
        if mode == "forward":
            await self.bot.forward_message(chat_id=user_id, from_chat_id=from_chat_id, message_id=message_id)
        else:
            await self.bot.copy_message(chat_id=user_id, from_chat_id=from_chat_id, message_id=message_id)

    async def _deliver(self, user_id: int, from_chat_id: int, message_id: int, mode: str) -> None:
        for attempt in range(3):
            wait = self._pause_until - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            try:
                await self._send_one(user_id, from_chat_id, message_id, mode)
                self.stats["sent"] += 1
                return
            except TelegramRetryAfter as e:
                # Telegram tezlikni cheklasa — hamma vazifalar birga kutadi
                self._pause_until = max(self._pause_until, time.monotonic() + float(e.retry_after) + 0.5)
                continue
            except (TelegramForbiddenError, TelegramNotFound):
                self.stats["blocked"] += 1
                await repo.set_user_active(user_id, False)
                return
            except TelegramBadRequest as e:
                text = str(e).lower()
                if "deactivated" in text or "chat not found" in text or "user not found" in text:
                    self.stats["blocked"] += 1
                    await repo.set_user_active(user_id, False)
                else:
                    self.stats["failed"] += 1
                return
            except TelegramAPIError:
                if attempt == 2:
                    self.stats["failed"] += 1
                    return
                await asyncio.sleep(1.0)
            except Exception as e:  # noqa: BLE001
                log.exception("Broadcast xatosi (%s): %s", user_id, e)
                self.stats["failed"] += 1
                return
        self.stats["failed"] += 1

    def _report(self, started: float, final: bool, stopped: bool) -> str:
        s = self.stats
        elapsed = int(time.monotonic() - started)
        done = s["sent"] + s["blocked"] + s["failed"]
        if stopped:
            head = "⏹ <b>Reklama to'xtatildi</b>"
        elif final:
            head = "✅ <b>Reklama yuborib bo'lindi</b>"
        else:
            head = "📤 <b>Reklama yuborilmoqda...</b>"
        speed = int(done * 60 / elapsed) if elapsed > 0 else 0
        return (
            f"{head}\n\n"
            f"👥 Jami: {s['total']}\n"
            f"✅ Yuborildi: {s['sent']}\n"
            f"🚫 Botni bloklagan: {s['blocked']}\n"
            f"❌ Xato: {s['failed']}\n"
            f"⏳ Qoldi: {max(0, s['total'] - done)}\n"
            f"⚡️ Tezlik: ~{speed} ta/daqiqa\n"
            f"🕐 Vaqt: {elapsed // 60} daq {elapsed % 60} s"
        )

    async def _run(
        self,
        admin_chat_id: int,
        from_chat_id: int,
        message_id: int,
        mode: str,
        stop_markup: InlineKeyboardMarkup | None,
    ) -> None:
        user_ids = await repo.all_broadcast_user_ids()
        self.stats = {"total": len(user_ids), "sent": 0, "blocked": 0, "failed": 0}
        interval = 60.0 / float(self.cfg.broadcast_per_minute)
        started = time.monotonic()
        semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
        tasks: set[asyncio.Task] = set()

        try:
            progress = await self.bot.send_message(admin_chat_id, self._report(started, False, False), reply_markup=stop_markup)
        except TelegramAPIError:
            progress = None

        async def worker(uid: int) -> None:
            async with semaphore:
                await self._deliver(uid, from_chat_id, message_id, mode)

        last_report = time.monotonic()
        stopped = False
        for index, user_id in enumerate(user_ids):
            if self._stop.is_set():
                stopped = True
                break
            # aniq tezlik: i-chi xabar started + i*interval da yuboriladi (pauzalar hisobga olinadi)
            slot = started + index * interval
            wait = max(slot, self._pause_until) - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            await semaphore.acquire()
            semaphore.release()
            task = asyncio.create_task(worker(user_id))
            tasks.add(task)
            task.add_done_callback(tasks.discard)

            if progress is not None and time.monotonic() - last_report >= REPORT_EVERY:
                last_report = time.monotonic()
                try:
                    await progress.edit_text(self._report(started, False, False), reply_markup=stop_markup)
                except TelegramAPIError:
                    pass

        if tasks:
            await asyncio.gather(*list(tasks), return_exceptions=True)

        final_text = self._report(started, True, stopped)
        sent_final = False
        if progress is not None:
            try:
                await progress.edit_text(final_text, reply_markup=None)
                sent_final = True
            except TelegramAPIError:
                pass
        if not sent_final:
            try:
                await self.bot.send_message(admin_chat_id, final_text)
            except TelegramAPIError:
                pass

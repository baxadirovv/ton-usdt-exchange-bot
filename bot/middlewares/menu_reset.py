"""
Asosiy menyu tugmasi (yoki /start, /admin) bosilganda joriy FSM holatini tozalaydi.
Shunda foydalanuvchi istalgan jarayon o'rtasida menyuga qaytishi mumkin.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from .. import texts

RESET_COMMANDS = ("/start", "/admin", "/menu", "/id")


class MenuResetMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Message) and event.text:
            text = event.text.strip()
            is_menu = text in texts.MENU_BUTTONS
            is_cmd = any(text == c or text.startswith(c + " ") or text.startswith(c + "@") for c in RESET_COMMANDS)
            if is_menu or is_cmd:
                state = data.get("state")
                if state is not None and data.get("raw_state") is not None:
                    await state.clear()
                    data["raw_state"] = None
        return await handler(event, data)

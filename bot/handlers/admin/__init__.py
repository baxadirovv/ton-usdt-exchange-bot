"""Admin panel routerlari (faqat adminlar uchun)."""
from __future__ import annotations

from aiogram import Router
from aiogram.types import TelegramObject

from . import broadcast, channels, orders, panel, users


async def admin_only(event: TelegramObject, is_admin: bool = False) -> bool:
    return bool(is_admin)


router = Router(name="admin")
router.message.filter(admin_only)
router.callback_query.filter(admin_only)
router.include_routers(orders.router, panel.router, users.router, broadcast.router, channels.router)

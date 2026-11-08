"""Inline tugmalar uchun callback data sinflari."""
from __future__ import annotations

from aiogram.filters.callback_data import CallbackData


class ExchangeCB(CallbackData, prefix="ex"):
    action: str     # buy | sell
    currency: str   # TON | USDT


class StockAlertCB(CallbackData, prefix="alert"):
    currency: str


class BuyConfirmCB(CallbackData, prefix="buyc"):
    action: str     # ok | no


class SimpleCB(CallbackData, prefix="s"):
    action: str     # cancel | topup | check_sub | hist_detail | guide_menu ...


class TopupCB(CallbackData, prefix="topup"):
    action: str     # cancel
    payment_id: int


class HistoryCB(CallbackData, prefix="hist"):
    page: int


class GuideCB(CallbackData, prefix="guide"):
    topic: str


# ---------------- Admin ----------------
class AdmSellCB(CallbackData, prefix="asell"):
    action: str     # ok | no
    order_id: int


class AdmUserCB(CallbackData, prefix="auser"):
    action: str     # add | sub | block | unblock | refresh
    user_id: int


class AdmSetCB(CallbackData, prefix="aset"):
    key: str        # sozlama kaliti yoki amal nomi


class AdmChanCB(CallbackData, prefix="achan"):
    action: str     # add | edit | list | pick | rename | delete | back
    channel_id: int = 0


class AdmBroadcastCB(CallbackData, prefix="abc"):
    action: str     # forward | copy | cancel


class AdmOrderCB(CallbackData, prefix="aord"):
    action: str     # refund | done
    order_id: int

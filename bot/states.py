"""FSM holatlari."""
from aiogram.fsm.state import State, StatesGroup


class BuyState(StatesGroup):
    amount = State()
    address = State()
    confirm = State()


class SellState(StatesGroup):
    amount = State()
    screenshot = State()
    card = State()


class TopupState(StatesGroup):
    amount = State()


class HistoryState(StatesGroup):
    order_id = State()


# ---------------- Admin ----------------
class AdminSetState(StatesGroup):
    value = State()          # bitta sozlama qiymatini kutish (data: key)


class AdminUserState(StatesGroup):
    user_id = State()        # boshqariladigan user ID
    amount = State()         # qo'shish/ayirish summasi (data: user_id, action)


class AdminBroadcastState(StatesGroup):
    message = State()
    confirm = State()


class AdminChannelState(StatesGroup):
    add_username = State()
    rename_username = State()  # data: channel_id

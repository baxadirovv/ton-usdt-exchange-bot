"""
TON (Gram) va USDT ayirboshlash boti — ishga tushirish fayli.

    python main.py
"""
import asyncio
import sys

if sys.version_info < (3, 10):
    sys.exit("❌ Python 3.10 yoki undan yangi versiya kerak (tavsiya: 3.12).")

from bot.app import main  # noqa: E402

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

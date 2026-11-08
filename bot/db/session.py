"""Bazaga ulanish (engine) va sessiya yaratish."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy import event, inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from .models import Base

_engine = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def setup_engine(database_url: str) -> None:
    """Engine yaratadi.

    SQLite uchun: bitta ulanish (barcha yozuvlar navbat bilan — "database is locked"
    xatosi va poyga holatlari bo'lmaydi), WAL rejimi, papka avtomatik yaratiladi.
    PostgreSQL/MySQL uchun: odatiy ulanishlar puli.
    """
    global _engine, _sessionmaker

    if database_url.startswith("sqlite"):
        path = database_url.split("///", 1)[-1]
        in_memory = (not path) or path == ":memory:" or "mode=memory" in path
        if not in_memory:
            os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
            _engine = create_async_engine(database_url, pool_size=1, max_overflow=0, pool_timeout=60)
        else:
            # Xotiradagi baza (asosan testlar): barcha sessiyalar BITTA ulanishni bo'lishadi. Havzaning "qaytarishda
            # rollback"i esa tugagan sessiya yopilganda boshqa sessiyaning hali commit qilinmagan yozuvini ham
            # bekor qilib yuborishi mumkin (kam uchraydigan poyga) — shuning uchun o'chirilgan.
            _engine = create_async_engine(database_url, poolclass=StaticPool, pool_reset_on_return=None)

        @event.listens_for(_engine.sync_engine, "connect")
        def _sqlite_pragmas(dbapi_connection, _record):  # pragma: no cover - driver hook
            cursor = dbapi_connection.cursor()
            try:
                if not in_memory:
                    cursor.execute("PRAGMA journal_mode=WAL")
                    cursor.execute("PRAGMA synchronous=NORMAL")
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA busy_timeout=10000")
            finally:
                cursor.close()
    elif database_url.startswith("mysql"):
        # MySQL / MariaDB: uzilgan ulanishlarni tekshirish, hosting wait_timeout dan oldin yangilash,
        # READ COMMITTED — qisqa qulflar va har doim eng yangi ma'lumot
        _engine = create_async_engine(
            database_url,
            pool_pre_ping=True,
            pool_recycle=280,
            pool_size=5,
            max_overflow=10,
            pool_timeout=30,
            isolation_level="READ COMMITTED",
        )
    else:
        _engine = create_async_engine(database_url, pool_pre_ping=True, pool_size=10, max_overflow=10)

    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)


def _add_missing_columns(sync_conn) -> None:
    """Yangi versiyada qo'shilgan ustunlarni mavjud jadvallarga qo'shadi (oddiy avto-migratsiya)."""
    inspector = inspect(sync_conn)
    for table in Base.metadata.sorted_tables:
        if not inspector.has_table(table.name):
            continue
        existing = {c["name"] for c in inspector.get_columns(table.name)}
        quote = sync_conn.dialect.identifier_preparer.quote
        for column in table.columns:
            if column.name in existing or not column.nullable:
                continue
            col_type = column.type.compile(dialect=sync_conn.dialect)
            sync_conn.execute(text(f"ALTER TABLE {quote(table.name)} ADD COLUMN {quote(column.name)} {col_type} NULL"))


async def init_db() -> None:
    """Jadvallarni yaratadi (mavjud bo'lsa tegmaydi) va yetishmayotgan ustunlarni qo'shadi."""
    assert _engine is not None, "setup_engine() avval chaqirilishi kerak"
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_add_missing_columns)


async def reset_db() -> None:
    """Barcha jadvallarni o'chirib qayta yaratadi (faqat testlar uchun)."""
    assert _engine is not None
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)


async def dispose_engine() -> None:
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """`async with session_scope() as s:` — oxirida commit, xatoda rollback.

    Diqqat: bitta session_scope ichida boshqa session_scope ochmang (SQLite bitta ulanishda ishlaydi).
    """
    assert _sessionmaker is not None, "setup_engine() avval chaqirilishi kerak"
    session = _sessionmaker()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()

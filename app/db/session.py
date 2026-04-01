"""Async engine and session factory."""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.db.base import Base

_engine: AsyncEngine | None = None
async_session_factory: async_sessionmaker | None = None


def _ensure_sqlite_parent_dir(database_url: str) -> None:
    """Create parent directory for on-disk SQLite files (Docker + local paths).

    Parses the URL with SQLAlchemy — the old split-on-``sqlite+aiosqlite/`` approach
    did not match real URLs (``sqlite+aiosqlite://...``), so the whole DSN was treated
    as a path on Windows.
    """
    if ":memory:" in database_url:
        return
    try:
        url = make_url(database_url)
    except Exception:
        return
    if not url.drivername.startswith("sqlite"):
        return
    db = url.database
    if not db or db == ":memory:":
        return
    # SQLAlchemy form ``sqlite:////C:/path`` → database ``/C:/path``
    if (
        os.name == "nt"
        and len(db) >= 3
        and db[0] == "/"
        and db[1].isalpha()
        and db[2] == ":"
    ):
        p = Path(db[1:])
    else:
        p = Path(db).expanduser()
        if not p.is_absolute():
            p = Path.cwd() / p
    p = p.resolve()
    p.parent.mkdir(parents=True, exist_ok=True)


def get_engine(database_url: str) -> AsyncEngine:
    global _engine
    if _engine is None:
        _ensure_sqlite_parent_dir(database_url)
        _engine = create_async_engine(
            database_url,
            echo=False,
            future=True,
        )
    return _engine


def get_session_factory(database_url: str) -> async_sessionmaker:
    global async_session_factory
    if async_session_factory is None:
        engine = get_engine(database_url)
        async_session_factory = async_sessionmaker(
            engine,
            expire_on_commit=False,
            autoflush=False,
        )
    return async_session_factory


async def init_db(database_url: str) -> None:
    """Create tables if they do not exist."""
    engine = get_engine(database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose_engine() -> None:
    global _engine, async_session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
    async_session_factory = None

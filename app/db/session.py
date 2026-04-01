"""Async engine and session factory."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.db.base import Base

_engine: AsyncEngine | None = None
async_session_factory: async_sessionmaker | None = None


def get_engine(database_url: str) -> AsyncEngine:
    global _engine
    if _engine is None:
        if "sqlite+aiosqlite" in database_url and ":memory:" not in database_url:
            path = database_url.split("sqlite+aiosqlite/", 1)[-1].lstrip("/")
            if path:
                p = Path(path).expanduser()
                if not p.is_absolute():
                    p = Path.cwd() / p
                p.parent.mkdir(parents=True, exist_ok=True)
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

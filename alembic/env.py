"""Alembic env — sync engine for SQLite migrations."""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool
from sqlalchemy.engine.url import make_url

from alembic import context

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.db.base import Base
from app.db.models import Task  # noqa: F401 — register models

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _sync_url_from_env_or_ini() -> str:
    """Match API ``DATABASE_URL`` (async) with a sync URL for Alembic."""
    dsn = os.environ.get("DATABASE_URL")
    if dsn and ":memory:" not in dsn:
        u = make_url(dsn)
        if u.drivername == "sqlite+aiosqlite":
            return str(u.set(drivername="sqlite"))
        return str(u)
    return config.get_main_option("sqlalchemy.url")


def run_migrations_offline() -> None:
    url = _sync_url_from_env_or_ini()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _sync_url_from_env_or_ini()
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

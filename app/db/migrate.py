"""Synchronous Alembic migrations at API startup (Docker + local file SQLite).

In-memory SQLite (tests) skips Alembic: ``create_all`` already matches models.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine.url import make_url

from app.db.session import _ensure_sqlite_parent_dir

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_ALEMBIC_INI = _PROJECT_ROOT / "alembic.ini"


def _async_to_sync_sqlalchemy_url(database_url: str) -> str:
    u = make_url(database_url)
    if u.drivername == "sqlite+aiosqlite":
        return str(u.set(drivername="sqlite"))
    return database_url


def _is_memory_sqlite(database_url: str) -> bool:
    return ":memory:" in database_url


def _alembic_config(sync_url: str) -> Config:
    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", sync_url)
    return cfg


def upgrade_database(database_url: str) -> None:
    """Apply Alembic revisions through *head* for on-disk databases.

    If *tasks* existed from an older ``create_all``-only deployment without
    ``alembic_version``, stamps an appropriate revision so *upgrade* can add
    missing columns without failing on *create_table*.
    """
    if _is_memory_sqlite(database_url):
        logger.debug("Skipping Alembic for in-memory SQLite (tests)")
        return

    _ensure_sqlite_parent_dir(database_url)
    sync_url = _async_to_sync_sqlalchemy_url(database_url)
    cfg = _alembic_config(sync_url)
    engine = create_engine(sync_url, pool_pre_ping=True, future=True)
    try:
        with engine.connect() as conn:
            inspector = inspect(conn)
            tables = set(inspector.get_table_names())
            if "alembic_version" not in tables and "tasks" in tables:
                cols = {c["name"] for c in inspector.get_columns("tasks")}
                if "latency_ms" in cols:
                    logger.info(
                        "Stamping database at Alembic head (existing tasks schema matches current)"
                    )
                    command.stamp(cfg, "head")
                else:
                    logger.info(
                        "Stamping database at 001 (existing tasks table; applying pending revisions)"
                    )
                    command.stamp(cfg, "001")
        command.upgrade(cfg, "head")
    finally:
        engine.dispose()


def cli_upgrade() -> None:
    """Entrypoint for scripts: use ``DATABASE_URL`` or default from settings."""
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        from app.settings import get_settings

        dsn = get_settings().database_url
    upgrade_database(dsn)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    cli_upgrade()

"""
SecurityOS database access — Phase 3

When DATABASE_URL is set, every repository uses PostgreSQL.  When it is not,
repositories fall back to in-memory implementations — allowed only in dev/test
(the app refuses to start in prod without a database; see securityos_main.py).

Accepted URL forms (normalised to the psycopg 3 driver):
  postgresql://user:pass@host:5432/db
  postgres://user:pass@host:5432/db
  postgresql+psycopg://user:pass@host:5432/db

Azure Database for PostgreSQL requires TLS: append `?sslmode=require`.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator, Optional

from sqlalchemy import create_engine
from sqlalchemy.engine import Connection, Engine

_engine: Optional[Engine] = None


def database_url() -> Optional[str]:
    raw = os.environ.get("DATABASE_URL", "").strip()
    if not raw:
        return None
    if raw.startswith("postgres://"):
        raw = "postgresql://" + raw[len("postgres://"):]
    if raw.startswith("postgresql://"):
        raw = "postgresql+psycopg://" + raw[len("postgresql://"):]
    return raw


def is_enabled() -> bool:
    return database_url() is not None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        url = database_url()
        if url is None:
            raise RuntimeError("DATABASE_URL is not set.")
        _engine = create_engine(
            url,
            pool_pre_ping=True,
            pool_size=int(os.environ.get("DB_POOL_SIZE", "5")),
            max_overflow=int(os.environ.get("DB_MAX_OVERFLOW", "5")),
            future=True,
        )
    return _engine


@contextmanager
def transaction() -> Iterator[Connection]:
    """One connection, one transaction: commits on success, rolls back on error."""
    with get_engine().begin() as conn:
        yield conn


def dispose() -> None:
    global _engine
    if _engine is not None:
        _engine.dispose()
        _engine = None

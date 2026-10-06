"""
Apply database migrations.  Run before starting the API:

    python -m backend.db.migrate            # upgrade to latest
    python -m backend.db.migrate --check    # exit 1 if migrations are pending

The container entrypoint runs this automatically.
"""

import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

from backend.db import get_engine

_INI = Path(__file__).resolve().parent.parent / "alembic.ini"


def alembic_config() -> Config:
    return Config(str(_INI))


def upgrade() -> None:
    command.upgrade(alembic_config(), "head")


def pending() -> bool:
    script = ScriptDirectory.from_config(alembic_config())
    with get_engine().connect() as conn:
        current = MigrationContext.configure(conn).get_current_revision()
    return current != script.get_current_head()


if __name__ == "__main__":
    if "--check" in sys.argv:
        sys.exit(1 if pending() else 0)
    upgrade()
    print("Database is up to date.")

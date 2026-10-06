"""Postgres: user directory."""

from __future__ import annotations

from typing import Dict, Iterable, Optional

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from backend.db import transaction
from backend.db.schema import users
from backend.repositories.sql._util import now_utc, to_iso
from backend.repositories.user_repo import User


class SqlUserRepository:
    def upsert(self, user_id: str, email: Optional[str], display_name: Optional[str]) -> None:
        now = now_utc()
        stmt = insert(users).values(user_id=user_id, email=email, display_name=display_name,
                                    first_seen=now, last_seen=now)
        stmt = stmt.on_conflict_do_update(
            index_elements=[users.c.user_id],
            set_={
                "email": func.coalesce(stmt.excluded.email, users.c.email),
                "display_name": func.coalesce(stmt.excluded.display_name, users.c.display_name),
                "last_seen": now,
            },
        )
        with transaction() as conn:
            conn.execute(stmt)

    def get_many(self, user_ids: Iterable[str]) -> Dict[str, User]:
        ids = list(set(user_ids))
        if not ids:
            return {}
        with transaction() as conn:
            rows = conn.execute(select(users).where(users.c.user_id.in_(ids))).all()
        return {
            r.user_id: User(r.user_id, r.email, r.display_name, to_iso(r.first_seen), to_iso(r.last_seen))
            for r in rows
        }

    def _clear(self) -> None:  # pragma: no cover
        pass

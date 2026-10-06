"""
User directory — Phase 3

A lightweight cache of who people are (email, display name), refreshed from
their verified JWT whenever they call /me, create an org, or accept an invite.
Used to show names instead of raw user IDs (assignee pickers, member lists).
It is never used for authorization.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional


@dataclass
class User:
    user_id: str
    email: Optional[str]
    display_name: Optional[str]
    first_seen: str
    last_seen: str


class InMemoryUserRepository:
    def __init__(self) -> None:
        self._users: Dict[str, User] = {}
        self._lock = threading.Lock()

    def upsert(self, user_id: str, email: Optional[str], display_name: Optional[str]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            u = self._users.get(user_id)
            if u is None:
                self._users[user_id] = User(user_id, email, display_name, now, now)
            else:
                u.email = email or u.email
                u.display_name = display_name or u.display_name
                u.last_seen = now

    def get_many(self, user_ids: Iterable[str]) -> Dict[str, User]:
        ids = set(user_ids)
        with self._lock:
            return {k: v for k, v in self._users.items() if k in ids}

    def _clear(self) -> None:
        with self._lock:
            self._users.clear()


def _build():
    from backend import db
    if db.is_enabled():
        from backend.repositories.sql.users import SqlUserRepository
        return SqlUserRepository()
    return InMemoryUserRepository()


user_repo = _build()


def describe(user_ids: Iterable[str]) -> List[Dict]:
    """[{user_id, email, display_name}] for API responses; unknown users get only an id."""
    ids = list(dict.fromkeys(user_ids))
    known = user_repo.get_many(ids)
    out = []
    for uid in ids:
        u = known.get(uid)
        out.append({
            "user_id": uid,
            "email": u.email if u else None,
            "display_name": (u.display_name if u else None) or uid,
        })
    return out

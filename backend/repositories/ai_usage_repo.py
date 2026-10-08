"""
AI usage repositories — v1 shadow AI.

  observations — current state: one row per (org, app), merged across imports
                 (mutable; replaced on each merge).
  decisions    — append-only history of approve / block / accept-risk calls.
                 The current decision is the latest record; nothing is edited.

In-memory implementation for dev/test, Postgres when DATABASE_URL is set.
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

from backend.ai_governance.observations import merge


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_decision(*, app_key: str, decision: str, note: Optional[str], expires_at: Optional[str],
                 decided_by_user_id: str, decided_by_name: str) -> Dict:
    return {
        "decision_id": f"aid_{uuid.uuid4().hex[:20]}",
        "app_key": app_key,
        "decision": decision,
        "note": note,
        "expires_at": expires_at,
        "decided_by_user_id": decided_by_user_id,
        "decided_by_name": decided_by_name,
        "decided_at": _now(),
    }


class InMemoryAiUsageRepository:
    def __init__(self) -> None:
        self._obs: Dict[str, Dict[str, Dict]] = {}
        self._decisions: Dict[str, List[Dict]] = {}
        self._lock = threading.Lock()

    def merge_observations(self, org_id: str, incoming: List[Dict]) -> int:
        now = _now()
        with self._lock:
            store = self._obs.setdefault(org_id, {})
            for o in incoming:
                store[o["app_key"]] = merge(store.get(o["app_key"]), o, updated_at=now)
            return len(incoming)

    def list_observations(self, org_id: str) -> List[Dict]:
        with self._lock:
            return [dict(o) for o in self._obs.get(org_id, {}).values()]

    def get_observation(self, org_id: str, app_key: str) -> Optional[Dict]:
        with self._lock:
            o = self._obs.get(org_id, {}).get(app_key)
            return dict(o) if o else None

    def add_decision(self, org_id: str, record: Dict) -> Dict:
        with self._lock:
            self._decisions.setdefault(org_id, []).append(dict(record))
            return dict(record)

    def list_decisions(self, org_id: str) -> List[Dict]:
        """Chronological."""
        with self._lock:
            return [dict(d) for d in self._decisions.get(org_id, [])]

    def remove_org(self, org_id: str) -> None:
        # Decision history is kept (append-only, like attestations); current
        # observations go with the org.
        with self._lock:
            self._obs.pop(org_id, None)

    def _clear(self) -> None:
        with self._lock:
            self._obs.clear()
            self._decisions.clear()


def _build():
    from backend import db
    if db.is_enabled():
        from backend.repositories.sql.ai_usage import SqlAiUsageRepository
        return SqlAiUsageRepository()
    return InMemoryAiUsageRepository()


ai_usage_repo = _build()

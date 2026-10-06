"""
Audit log — Phase 3: append-only and hash-chained.

Every security-relevant action (org creation, role grants, invites, manual
status changes, attestations) is recorded here.  There is no update or delete
API, and in Postgres the table rejects UPDATE/DELETE/TRUNCATE via triggers.

Tamper evidence:
  Each org has its own chain.  For each event:
      row_hash = sha256(prev_hash || canonical_json(event))
  where prev_hash is the previous event's row_hash in the same chain
  (GENESIS for the first).  `verify(org_id)` recomputes every hash and reports
  the first row whose stored hash no longer matches — i.e. the first row that
  was edited, inserted out of order, or followed by a deleted row.
"""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

GENESIS_HASH = "0" * 64
GLOBAL_CHAIN = "__global__"


def chain_key(org_id: Optional[str]) -> str:
    return org_id or GLOBAL_CHAIN


def normalize_ts(value: datetime) -> str:
    """Canonical timestamp string used inside the hash (UTC, microsecond precision)."""
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def canonical_event(*, event_id: str, chain: str, org_id: Optional[str], actor_user_id: str,
                    action: str, occurred_at: str, details: Dict[str, Any]) -> str:
    return json.dumps(
        {
            "event_id": event_id,
            "chain_key": chain,
            "org_id": org_id,
            "actor_user_id": actor_user_id,
            "action": action,
            "occurred_at": occurred_at,
            "details": details,
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def compute_hash(prev_hash: str, canonical: str) -> str:
    return hashlib.sha256((prev_hash + canonical).encode()).hexdigest()


def json_safe(details: Dict[str, Any]) -> Dict[str, Any]:
    """Round-trip through JSON so the hashed form equals what the DB stores and returns."""
    return json.loads(json.dumps(details, default=str))


@dataclass(frozen=True)
class AuditEvent:
    event_id: str
    org_id: Optional[str]
    actor_user_id: str
    action: str
    occurred_at: str
    details: Dict[str, Any] = field(default_factory=dict)
    seq: int = 0
    prev_hash: str = GENESIS_HASH
    row_hash: str = ""


def verify_chain(events: List[AuditEvent], chain: str) -> Dict[str, Any]:
    """Recompute a chain (events in seq order).  Shared by both implementations."""
    prev = GENESIS_HASH
    for e in events:
        expected = compute_hash(prev, canonical_event(
            event_id=e.event_id, chain=chain, org_id=e.org_id, actor_user_id=e.actor_user_id,
            action=e.action, occurred_at=e.occurred_at, details=e.details,
        ))
        if e.prev_hash != prev or e.row_hash != expected:
            return {"valid": False, "checked": len(events), "first_break_seq": e.seq,
                    "first_break_event_id": e.event_id}
        prev = e.row_hash
    return {"valid": True, "checked": len(events), "first_break_seq": None,
            "first_break_event_id": None, "head_hash": prev}


class InMemoryAuditRepository:
    def __init__(self) -> None:
        self._events: List[AuditEvent] = []
        self._heads: Dict[str, str] = {}
        self._seq = 0
        self._lock = threading.Lock()

    def record(self, *, org_id: Optional[str], actor_user_id: str, action: str, **details: Any) -> AuditEvent:
        chain = chain_key(org_id)
        details = json_safe(details)
        with self._lock:
            self._seq += 1
            occurred = normalize_ts(datetime.now(timezone.utc))
            event_id = str(uuid.uuid4())
            prev = self._heads.get(chain, GENESIS_HASH)
            row_hash = compute_hash(prev, canonical_event(
                event_id=event_id, chain=chain, org_id=org_id, actor_user_id=actor_user_id,
                action=action, occurred_at=occurred, details=details,
            ))
            event = AuditEvent(event_id=event_id, org_id=org_id, actor_user_id=actor_user_id,
                               action=action, occurred_at=occurred, details=details,
                               seq=self._seq, prev_hash=prev, row_hash=row_hash)
            self._events.append(event)
            self._heads[chain] = row_hash
        return event

    def _chain(self, org_id: Optional[str]) -> List[AuditEvent]:
        with self._lock:
            return [e for e in self._events if chain_key(e.org_id) == chain_key(org_id)]

    def list_by_org(self, org_id: str) -> List[Dict[str, Any]]:
        return [asdict(e) for e in self._chain(org_id)]

    def verify(self, org_id: str) -> Dict[str, Any]:
        return verify_chain(self._chain(org_id), chain_key(org_id))

    def _tamper_for_tests(self, event_id: str, **changes: Any) -> None:
        """Test helper: simulate someone editing a stored row."""
        from dataclasses import replace
        with self._lock:
            for i, e in enumerate(self._events):
                if e.event_id == event_id:
                    self._events[i] = replace(e, **changes)

    def _clear(self) -> None:
        with self._lock:
            self._events.clear()
            self._heads.clear()


def _build():
    from backend import db
    if db.is_enabled():
        from backend.repositories.sql.audit import SqlAuditRepository
        return SqlAuditRepository()
    return InMemoryAuditRepository()


audit_repo = _build()

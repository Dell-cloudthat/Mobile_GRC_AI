"""Postgres: hash-chained, append-only audit log."""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select, text

from backend.db import transaction
from backend.db.schema import audit_log as al
from backend.repositories.audit_repo import (
    GENESIS_HASH,
    AuditEvent,
    canonical_event,
    chain_key,
    compute_hash,
    json_safe,
    normalize_ts,
    verify_chain,
)
from backend.repositories.sql._util import now_utc


def _row(r) -> AuditEvent:
    return AuditEvent(
        event_id=r.event_id, org_id=r.org_id, actor_user_id=r.actor_user_id, action=r.action,
        occurred_at=normalize_ts(r.occurred_at), details=dict(r.details or {}), seq=r.seq,
        prev_hash=r.prev_hash, row_hash=r.row_hash,
    )


class SqlAuditRepository:
    def record(self, *, org_id: Optional[str], actor_user_id: str, action: str, **details: Any) -> AuditEvent:
        chain = chain_key(org_id)
        details = json_safe(details)
        occurred_dt = now_utc()
        occurred = normalize_ts(occurred_dt)
        event_id = str(uuid.uuid4())
        with transaction() as conn:
            # Serialize writers per chain so two requests can't both extend the same head.
            conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": chain})
            prev = conn.execute(
                select(al.c.row_hash).where(al.c.chain_key == chain).order_by(al.c.seq.desc()).limit(1)
            ).scalar() or GENESIS_HASH
            row_hash = compute_hash(prev, canonical_event(
                event_id=event_id, chain=chain, org_id=org_id, actor_user_id=actor_user_id,
                action=action, occurred_at=occurred, details=details,
            ))
            seq = conn.execute(al.insert().values(
                event_id=event_id, chain_key=chain, org_id=org_id, actor_user_id=actor_user_id,
                action=action, occurred_at=occurred_dt, details=details, prev_hash=prev, row_hash=row_hash,
            ).returning(al.c.seq)).scalar_one()
        return AuditEvent(event_id=event_id, org_id=org_id, actor_user_id=actor_user_id, action=action,
                          occurred_at=occurred, details=details, seq=seq, prev_hash=prev, row_hash=row_hash)

    def _chain(self, org_id: Optional[str]) -> List[AuditEvent]:
        with transaction() as conn:
            rows = conn.execute(select(al).where(al.c.chain_key == chain_key(org_id)).order_by(al.c.seq)).all()
        return [_row(r) for r in rows]

    def list_by_org(self, org_id: str) -> List[Dict[str, Any]]:
        from dataclasses import asdict
        return [asdict(e) for e in self._chain(org_id)]

    def verify(self, org_id: str) -> Dict[str, Any]:
        return verify_chain(self._chain(org_id), chain_key(org_id))

    def count(self) -> int:
        with transaction() as conn:
            return conn.execute(select(func.count()).select_from(al)).scalar_one()

    def _clear(self) -> None:  # pragma: no cover
        pass

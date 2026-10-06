"""Postgres: manual statuses (mutable) and attestations + revocations (append-only)."""

from __future__ import annotations

from typing import Dict, List, Optional

from sqlalchemy import and_, delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError

from backend.db import transaction
from backend.db.schema import attestation_revocations as rv
from backend.db.schema import attestations as at
from backend.db.schema import manual_statuses as ms
from backend.evidence.attestation import (
    Attestation,
    AttestationScope,
    AttestationStatus,
    AttestationType,
)
from backend.repositories.control_state_repo import apply_revocation
from backend.repositories.sql._util import now_utc, to_dt, to_iso


class SqlManualStatusRepository:
    def set(self, org_id: str, control_id: str, entry: Dict) -> None:
        values = dict(
            org_id=org_id, control_id=control_id, status=entry["status"], notes=entry.get("notes"),
            evidence_source=entry.get("evidence_source", "manual"),
            last_checked=to_dt(entry.get("last_checked")) or now_utc(), set_by=entry["set_by"],
        )
        stmt = insert(ms).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=[ms.c.org_id, ms.c.control_id],
            set_={k: stmt.excluded[k] for k in ("status", "notes", "evidence_source", "last_checked", "set_by")},
        )
        with transaction() as conn:
            conn.execute(stmt)

    def get_all(self, org_id: str) -> Dict[str, Dict]:
        with transaction() as conn:
            rows = conn.execute(select(ms).where(ms.c.org_id == org_id)).all()
        return {
            r.control_id: {
                "status": r.status, "notes": r.notes, "evidence_source": r.evidence_source,
                "last_checked": to_iso(r.last_checked), "set_by": r.set_by,
            }
            for r in rows
        }

    def remove_org(self, org_id: str) -> None:
        with transaction() as conn:
            conn.execute(delete(ms).where(ms.c.org_id == org_id))

    def _clear(self) -> None:  # pragma: no cover
        pass


def _attest(r) -> Attestation:
    created = to_iso(r.created_at)
    return Attestation(
        id=r.id, organization_id=r.organization_id, created_by_user_id=r.created_by_user_id,
        created_by_name=r.created_by_name, created_by_email=r.created_by_email,
        attestation_type=AttestationType(r.attestation_type), scope_type=AttestationScope(r.scope_type),
        control_ids=list(r.control_ids), source_provider_id=r.source_provider_id,
        source_name=r.source_name, source_description=r.source_description, statement=r.statement,
        status=AttestationStatus.ACTIVE, effective_at=to_iso(r.effective_at),
        expires_at=to_iso(r.expires_at), validity_days=r.validity_days, created_at=created,
        updated_at=created, ip_address=r.ip_address, user_agent=r.user_agent,
        metadata=dict(r.metadata or {}),
    )


def _revocation(r) -> Optional[Dict]:
    if r is None:
        return None
    return {"revoked_at": to_iso(r.revoked_at), "revoked_by_user_id": r.revoked_by_user_id,
            "revoked_by_name": r.revoked_by_name, "reason": r.reason}


class SqlAttestationRepository:
    def add(self, a: Attestation) -> None:
        with transaction() as conn:
            conn.execute(at.insert().values(
                id=a.id, organization_id=a.organization_id, created_by_user_id=a.created_by_user_id,
                created_by_name=a.created_by_name, created_by_email=a.created_by_email,
                attestation_type=getattr(a.attestation_type, "value", a.attestation_type),
                scope_type=getattr(a.scope_type, "value", a.scope_type),
                control_ids=list(a.control_ids), source_provider_id=a.source_provider_id,
                source_name=a.source_name, source_description=a.source_description, statement=a.statement,
                effective_at=to_dt(a.effective_at), expires_at=to_dt(a.expires_at),
                validity_days=a.validity_days, created_at=to_dt(a.created_at), ip_address=a.ip_address,
                user_agent=a.user_agent, metadata=a.metadata or {},
            ))

    def get(self, org_id: str, attest_id: str) -> Optional[Attestation]:
        with transaction() as conn:
            r = conn.execute(select(at).where(and_(at.c.id == attest_id, at.c.organization_id == org_id))).first()
            if r is None:
                return None
            rev = conn.execute(select(rv).where(rv.c.attestation_id == attest_id)).first()
        return apply_revocation(_attest(r), _revocation(rev))

    def list_by_org(self, org_id: str) -> List[Attestation]:
        with transaction() as conn:
            rows = conn.execute(select(at).where(at.c.organization_id == org_id).order_by(at.c.created_at)).all()
            revs = {r.attestation_id: r for r in conn.execute(select(rv).where(rv.c.org_id == org_id)).all()}
        return [apply_revocation(_attest(r), _revocation(revs.get(r.id))) for r in rows]

    def revoke(self, org_id: str, attest_id: str, *, revoked_by_user_id: Optional[str],
               revoked_by_name: str, reason: Optional[str]) -> Attestation:
        if self.get(org_id, attest_id) is None:
            raise LookupError(attest_id)
        try:
            with transaction() as conn:
                conn.execute(rv.insert().values(
                    attestation_id=attest_id, org_id=org_id, revoked_at=now_utc(),
                    revoked_by_user_id=revoked_by_user_id, revoked_by_name=revoked_by_name, reason=reason,
                ))
        except IntegrityError:
            raise ValueError("Attestation is already revoked.")
        return self.get(org_id, attest_id)

    def remove_org(self, org_id: str) -> None:
        """No-op: attestations are append-only and retained when an org is deleted."""

    def _clear(self) -> None:  # pragma: no cover
        pass

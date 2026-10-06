"""
Control-state repositories — Phase 3

Two inputs to scoring that are not findings:

  manual_status_repo  — fail / unknown / in_progress statuses set by a person.
                        (Score-raising values are rejected at the API layer.)
  attestation_repo    — executive attestations.  Append-only: revocation is a
                        separate record, never an edit; status (active /
                        expired / revoked) is derived when read.

Both have an in-memory implementation (dev/test) and a Postgres one, chosen by
DATABASE_URL.
"""

from __future__ import annotations

import threading
from dataclasses import replace
from datetime import datetime, timezone
from typing import Dict, List, Optional

from backend.evidence.attestation import Attestation, AttestationStatus


# ── Manual statuses ───────────────────────────────────────────────────────────

class InMemoryManualStatusRepository:
    def __init__(self) -> None:
        self._data: Dict[str, Dict[str, Dict]] = {}
        self._lock = threading.Lock()

    def set(self, org_id: str, control_id: str, entry: Dict) -> None:
        with self._lock:
            self._data.setdefault(org_id, {})[control_id] = dict(entry)

    def get_all(self, org_id: str) -> Dict[str, Dict]:
        with self._lock:
            return {k: dict(v) for k, v in self._data.get(org_id, {}).items()}

    def remove_org(self, org_id: str) -> None:
        with self._lock:
            self._data.pop(org_id, None)

    def _clear(self) -> None:
        with self._lock:
            self._data.clear()


# ── Attestations ──────────────────────────────────────────────────────────────

def apply_revocation(attest: Attestation, revocation: Optional[Dict]) -> Attestation:
    """Return a copy of `attest` with revocation fields/status applied (read-time derivation)."""
    if not revocation:
        return attest
    return replace(
        attest,
        status=AttestationStatus.REVOKED,
        revoked_at=revocation["revoked_at"],
        revoked_by_user_id=revocation.get("revoked_by_user_id"),
        revoked_by_name=revocation["revoked_by_name"],
        revoke_reason=revocation.get("reason"),
        updated_at=revocation["revoked_at"],
    )


class InMemoryAttestationRepository:
    def __init__(self) -> None:
        self._attests: Dict[str, Attestation] = {}          # id → immutable record
        self._revocations: Dict[str, Dict] = {}             # id → revocation record
        self._lock = threading.Lock()

    def add(self, attest: Attestation) -> None:
        with self._lock:
            if attest.id in self._attests:
                raise KeyError(f"Attestation '{attest.id}' already exists.")
            self._attests[attest.id] = replace(attest)

    def get(self, org_id: str, attest_id: str) -> Optional[Attestation]:
        with self._lock:
            a = self._attests.get(attest_id)
            if a is None or a.organization_id != org_id:
                return None
            return apply_revocation(replace(a), self._revocations.get(attest_id))

    def list_by_org(self, org_id: str) -> List[Attestation]:
        with self._lock:
            return [
                apply_revocation(replace(a), self._revocations.get(a.id))
                for a in self._attests.values() if a.organization_id == org_id
            ]

    def revoke(self, org_id: str, attest_id: str, *, revoked_by_user_id: Optional[str],
               revoked_by_name: str, reason: Optional[str]) -> Attestation:
        with self._lock:
            a = self._attests.get(attest_id)
            if a is None or a.organization_id != org_id:
                raise LookupError(attest_id)
            if attest_id in self._revocations:
                raise ValueError("Attestation is already revoked.")
            self._revocations[attest_id] = {
                "revoked_at": datetime.now(timezone.utc).isoformat(),
                "revoked_by_user_id": revoked_by_user_id,
                "revoked_by_name": revoked_by_name,
                "reason": reason,
            }
            return apply_revocation(replace(a), self._revocations[attest_id])

    def remove_org(self, org_id: str) -> None:
        with self._lock:
            for aid in [k for k, a in self._attests.items() if a.organization_id == org_id]:
                self._attests.pop(aid, None)
                self._revocations.pop(aid, None)

    def _clear(self) -> None:
        with self._lock:
            self._attests.clear()
            self._revocations.clear()


# ── Selection ─────────────────────────────────────────────────────────────────

def _build():
    from backend import db
    if db.is_enabled():
        from backend.repositories.sql.control_state import (
            SqlAttestationRepository,
            SqlManualStatusRepository,
        )
        return SqlManualStatusRepository(), SqlAttestationRepository()
    return InMemoryManualStatusRepository(), InMemoryAttestationRepository()


manual_status_repo, attestation_repo = _build()


def remove_org(org_id: str) -> None:
    manual_status_repo.remove_org(org_id)
    attestation_repo.remove_org(org_id)

"""
Organization repository — Phase 2.1

Single registry of organizations and their business profiles.  Org IDs are
always server-generated; a token's `org_id` claim is never used to create or
authorize access to an org.

Before Phase 2.1 the same client org could have two diverging profiles (one in
api._profiles, one inside the MSP store).  Both routers now read and write the
profile here.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass
class Organization:
    org_id: str
    name: str
    created_by: str                    # user_id
    created_at: str
    msp_id: Optional[str] = None       # set when provisioned by an MSP
    contact_email: Optional[str] = None
    notes: Optional[str] = None
    profile: Dict[str, Any] = field(default_factory=dict)
    updated_at: Optional[str] = None


def new_org_id() -> str:
    return f"org-{uuid.uuid4().hex[:12]}"


class InMemoryOrgRepository:
    def __init__(self) -> None:
        self._orgs: Dict[str, Organization] = {}
        self._lock = threading.Lock()

    def create(
        self,
        *,
        name: str,
        created_by: str,
        msp_id: Optional[str] = None,
        profile: Optional[Dict[str, Any]] = None,
        contact_email: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Organization:
        now = datetime.now(timezone.utc).isoformat()
        org = Organization(
            org_id=new_org_id(),
            name=name,
            created_by=created_by,
            created_at=now,
            updated_at=now,
            msp_id=msp_id,
            contact_email=contact_email,
            notes=notes,
            profile={"business_name": name, **(profile or {})},
        )
        with self._lock:
            self._orgs[org.org_id] = org
        return org

    def get(self, org_id: str) -> Optional[Organization]:
        with self._lock:
            return self._orgs.get(org_id)

    def list_by_msp(self, msp_id: str) -> List[Organization]:
        with self._lock:
            return [o for o in self._orgs.values() if o.msp_id == msp_id]

    def update_profile(self, org_id: str, profile: Dict[str, Any]) -> Organization:
        with self._lock:
            org = self._orgs[org_id]
            org.profile = {**org.profile, **profile}
            if profile.get("business_name"):
                org.name = profile["business_name"]
            org.updated_at = datetime.now(timezone.utc).isoformat()
            return org

    def update_fields(self, org_id: str, **fields: Any) -> Organization:
        """Update non-profile fields (contact_email, notes)."""
        allowed = {"contact_email", "notes"}
        with self._lock:
            org = self._orgs[org_id]
            for k, v in fields.items():
                if k not in allowed:
                    raise ValueError(f"Field '{k}' cannot be updated.")
                setattr(org, k, v)
            org.updated_at = datetime.now(timezone.utc).isoformat()
            return org

    def delete(self, org_id: str) -> None:
        with self._lock:
            self._orgs.pop(org_id, None)

    def _clear(self) -> None:
        with self._lock:
            self._orgs.clear()


def _build():
    from backend import db
    if db.is_enabled():
        from backend.repositories.sql.orgs import SqlOrgRepository
        return SqlOrgRepository()
    return InMemoryOrgRepository()


org_repo = _build()

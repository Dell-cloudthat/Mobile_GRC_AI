"""
OrgMembership repository — Phase 2.1 RBAC

Source of truth for role-based authorization within an organization.
Identity (who you are) comes from the JWT; authorization (what you may do)
comes from this table, never from token role claims.

Phase 2.1 changes:
  - Roles are ADDITIVE: one row per (user_id, org_id, role).  A user may hold
    several roles in the same org (e.g. admin + executive in a 3-person company).
  - expires_at is ENFORCED: expired rows are invisible to every read used for
    authorization (`active_roles`, `has_any_active`).  They remain stored for
    history and are visible via `list_by_org(include_expired=True)`.

Roles and their semantics (permission mapping lives in backend/auth/permissions.py):
  admin          — org management: members, invites, settings, billing. Cannot attest.
  executive      — sign-off: approve High/Critical fixes, attest, accept risk.
  engineer       — remediation: work findings, submit evidence.
  msp_technician — MSP staff servicing a client org: assign + remediate. Cannot attest.
  auditor        — time-boxed read-only access + audit export. expires_at required.

Schema (logical):
  org_memberships(user_id, org_id, role, granted_by, granted_at, expires_at)
  UNIQUE (user_id, org_id, role)
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, FrozenSet, List, Optional, Protocol, Set, Tuple


# ── Valid roles ────────────────────────────────────────────────────────────────

VALID_ROLES: FrozenSet[str] = frozenset(
    {"admin", "executive", "engineer", "msp_technician", "auditor"}
)

# Roles that must always carry an expiry date.
ROLES_REQUIRING_EXPIRY: FrozenSet[str] = frozenset({"auditor"})


# ── Time helpers ──────────────────────────────────────────────────────────────

def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_iso(value: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-8601 string into an aware UTC datetime.  Naive → UTC."""
    if not value:
        return None
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class OrgMembership:
    user_id: str
    org_id: str
    role: str                          # one of VALID_ROLES
    granted_by: str                    # user_id of the grantor ("system" for bootstrap)
    granted_at: str                    # ISO-8601 UTC timestamp (server-set)
    expires_at: Optional[str] = None   # ISO-8601 UTC or None

    def is_expired(self, now: Optional[datetime] = None) -> bool:
        exp = parse_iso(self.expires_at)
        if exp is None:
            return False
        return exp <= (now or utcnow())


# ── Repository protocol ───────────────────────────────────────────────────────

class OrgMembershipRepository(Protocol):
    def active_roles(self, user_id: str, org_id: str) -> Set[str]: ...
    def has_any_active(self, user_id: str, org_id: str) -> bool: ...
    def get_role(self, user_id: str, org_id: str, role: str) -> Optional[OrgMembership]: ...
    def list_by_org(self, org_id: str, *, include_expired: bool = False) -> List[OrgMembership]: ...
    def list_by_user(self, user_id: str, *, include_expired: bool = False) -> List[OrgMembership]: ...
    def add(self, membership: OrgMembership) -> None: ...
    def remove_role(self, user_id: str, org_id: str, role: str) -> bool: ...
    def remove_all(self, user_id: str, org_id: str) -> int: ...
    def remove_org(self, org_id: str) -> int: ...
    def _clear(self) -> None: ...


# ── In-memory implementation ──────────────────────────────────────────────────

class InMemoryOrgMembershipRepository:
    """Thread-safe in-memory implementation for development and testing."""

    def __init__(self) -> None:
        # Keyed by (user_id, org_id, role)
        self._data: Dict[Tuple[str, str, str], OrgMembership] = {}
        self._lock = threading.Lock()

    # ── Authorization reads (expiry enforced) ─────────────────────────────────

    def active_roles(self, user_id: str, org_id: str) -> Set[str]:
        now = utcnow()
        with self._lock:
            return {
                m.role
                for (u, o, _), m in self._data.items()
                if u == user_id and o == org_id and not m.is_expired(now)
            }

    def has_any_active(self, user_id: str, org_id: str) -> bool:
        return bool(self.active_roles(user_id, org_id))

    def get_role(self, user_id: str, org_id: str, role: str) -> Optional[OrgMembership]:
        """Return the row for a specific role, or None if absent OR expired."""
        with self._lock:
            m = self._data.get((user_id, org_id, role))
        if m is None or m.is_expired():
            return None
        return m

    # ── Listing ───────────────────────────────────────────────────────────────

    def list_by_org(self, org_id: str, *, include_expired: bool = False) -> List[OrgMembership]:
        now = utcnow()
        with self._lock:
            rows = [m for m in self._data.values() if m.org_id == org_id]
        if not include_expired:
            rows = [m for m in rows if not m.is_expired(now)]
        return sorted(rows, key=lambda m: (m.user_id, m.role))

    def list_by_user(self, user_id: str, *, include_expired: bool = False) -> List[OrgMembership]:
        now = utcnow()
        with self._lock:
            rows = [m for m in self._data.values() if m.user_id == user_id]
        if not include_expired:
            rows = [m for m in rows if not m.is_expired(now)]
        return sorted(rows, key=lambda m: (m.org_id, m.role))

    def users_with_role(self, org_id: str, role: str) -> List[str]:
        return [m.user_id for m in self.list_by_org(org_id) if m.role == role]

    # ── Writes ────────────────────────────────────────────────────────────────

    def add(self, membership: OrgMembership) -> None:
        if membership.role not in VALID_ROLES:
            raise ValueError(
                f"Invalid role '{membership.role}'. Must be one of {sorted(VALID_ROLES)}."
            )
        if membership.role in ROLES_REQUIRING_EXPIRY and not membership.expires_at:
            raise ValueError(f"Role '{membership.role}' requires an expires_at date.")
        key = (membership.user_id, membership.org_id, membership.role)
        with self._lock:
            existing = self._data.get(key)
            if existing is not None and not existing.is_expired():
                raise KeyError(
                    f"User '{membership.user_id}' already holds role '{membership.role}' "
                    f"in org '{membership.org_id}'."
                )
            # An expired row for the same role may be replaced by a fresh grant.
            self._data[key] = membership

    def remove_role(self, user_id: str, org_id: str, role: str) -> bool:
        with self._lock:
            return self._data.pop((user_id, org_id, role), None) is not None

    def remove_all(self, user_id: str, org_id: str) -> int:
        with self._lock:
            keys = [k for k in self._data if k[0] == user_id and k[1] == org_id]
            for k in keys:
                del self._data[k]
            return len(keys)

    def remove_org(self, org_id: str) -> int:
        with self._lock:
            keys = [k for k in self._data if k[1] == org_id]
            for k in keys:
                del self._data[k]
            return len(keys)

    def _clear(self) -> None:
        """Test helper: remove all memberships."""
        with self._lock:
            self._data.clear()


# ── Module-level singleton ────────────────────────────────────────────────────

def _build():
    from backend import db
    if db.is_enabled():
        from backend.repositories.sql.memberships import SqlOrgMembershipRepository
        return SqlOrgMembershipRepository()
    return InMemoryOrgMembershipRepository()


org_membership_repo = _build()

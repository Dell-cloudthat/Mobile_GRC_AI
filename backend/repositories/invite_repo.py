"""
Invite repository — Phase 2.1

Single-use, expiring, role-bound invitations.  This is how people join an org
(including how a client's executive joins an MSP-provisioned org).

Security properties:
  - The raw token is returned exactly once, at creation.  Only its SHA-256 hash
    is stored, so a leaked store cannot be replayed.
  - Each invite is bound to one org and one role, expires (default 7 days,
    max 30), and can be accepted once.
  - The accepting user's identity comes from their verified JWT, never from
    the invite or the request body.
"""

from __future__ import annotations

import hashlib
import secrets
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

DEFAULT_INVITE_DAYS = 7
MAX_INVITE_DAYS = 30


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass
class Invite:
    invite_id: str
    org_id: str
    role: str
    token_hash: str
    created_by: str
    created_at: str
    expires_at: str
    email_hint: Optional[str] = None           # display only; NOT enforced
    membership_expires_at: Optional[str] = None  # e.g. auditor access window
    accepted_by: Optional[str] = None
    accepted_at: Optional[str] = None
    revoked_at: Optional[str] = None

    @property
    def status(self) -> str:
        if self.revoked_at:
            return "revoked"
        if self.accepted_at:
            return "accepted"
        if datetime.fromisoformat(self.expires_at) <= datetime.now(timezone.utc):
            return "expired"
        return "pending"


class InMemoryInviteRepository:
    def __init__(self) -> None:
        self._by_hash: Dict[str, Invite] = {}
        self._lock = threading.Lock()

    def create(
        self,
        *,
        org_id: str,
        role: str,
        created_by: str,
        valid_days: int = DEFAULT_INVITE_DAYS,
        email_hint: Optional[str] = None,
        membership_expires_at: Optional[str] = None,
    ) -> Tuple[Invite, str]:
        """Create an invite and return (invite, raw_token).  raw_token is never stored."""
        if not 1 <= valid_days <= MAX_INVITE_DAYS:
            raise ValueError(f"valid_days must be between 1 and {MAX_INVITE_DAYS}.")
        raw = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        invite = Invite(
            invite_id=f"inv-{uuid.uuid4().hex[:12]}",
            org_id=org_id,
            role=role,
            token_hash=_hash(raw),
            created_by=created_by,
            created_at=now.isoformat(),
            expires_at=(now + timedelta(days=valid_days)).isoformat(),
            email_hint=email_hint,
            membership_expires_at=membership_expires_at,
        )
        with self._lock:
            self._by_hash[invite.token_hash] = invite
        return invite, raw

    def find_by_token(self, raw_token: str) -> Optional[Invite]:
        with self._lock:
            return self._by_hash.get(_hash(raw_token))

    def mark_accepted(self, invite: Invite, user_id: str) -> None:
        with self._lock:
            invite.accepted_by = user_id
            invite.accepted_at = datetime.now(timezone.utc).isoformat()

    def revoke(self, invite_id: str, org_id: str) -> Optional[Invite]:
        with self._lock:
            for inv in self._by_hash.values():
                if inv.invite_id == invite_id and inv.org_id == org_id:
                    if inv.revoked_at is None:
                        inv.revoked_at = datetime.now(timezone.utc).isoformat()
                    return inv
        return None

    def list_by_org(self, org_id: str) -> List[Invite]:
        with self._lock:
            return sorted(
                (i for i in self._by_hash.values() if i.org_id == org_id),
                key=lambda i: i.created_at,
            )

    def remove_org(self, org_id: str) -> None:
        with self._lock:
            for h in [h for h, i in self._by_hash.items() if i.org_id == org_id]:
                del self._by_hash[h]

    def _clear(self) -> None:
        with self._lock:
            self._by_hash.clear()


def _build():
    from backend import db
    if db.is_enabled():
        from backend.repositories.sql.invites import SqlInviteRepository
        return SqlInviteRepository()
    return InMemoryInviteRepository()


invite_repo = _build()

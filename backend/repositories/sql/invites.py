"""Postgres: invites (only token hashes are stored)."""

from __future__ import annotations

import secrets
import uuid
from datetime import timedelta
from typing import List, Optional, Tuple

from sqlalchemy import and_, select, update

from backend.db import transaction
from backend.db.schema import invites as t
from backend.repositories.invite_repo import MAX_INVITE_DAYS, Invite, _hash
from backend.repositories.sql._util import now_utc, to_dt, to_iso


def _row(r) -> Invite:
    return Invite(
        invite_id=r.invite_id, org_id=r.org_id, role=r.role, token_hash=r.token_hash,
        created_by=r.created_by, created_at=to_iso(r.created_at), expires_at=to_iso(r.expires_at),
        email_hint=r.email_hint, membership_expires_at=to_iso(r.membership_expires_at),
        accepted_by=r.accepted_by, accepted_at=to_iso(r.accepted_at), revoked_at=to_iso(r.revoked_at),
    )


class SqlInviteRepository:
    def create(self, *, org_id: str, role: str, created_by: str, valid_days: int = 7,
               email_hint: Optional[str] = None,
               membership_expires_at: Optional[str] = None) -> Tuple[Invite, str]:
        if not 1 <= valid_days <= MAX_INVITE_DAYS:
            raise ValueError(f"valid_days must be between 1 and {MAX_INVITE_DAYS}.")
        raw = secrets.token_urlsafe(32)
        now = now_utc()
        invite_id = f"inv-{uuid.uuid4().hex[:12]}"
        with transaction() as conn:
            conn.execute(t.insert().values(
                invite_id=invite_id, org_id=org_id, role=role, token_hash=_hash(raw),
                created_by=created_by, created_at=now, expires_at=now + timedelta(days=valid_days),
                email_hint=email_hint, membership_expires_at=to_dt(membership_expires_at),
            ))
            r = conn.execute(select(t).where(t.c.invite_id == invite_id)).one()
        return _row(r), raw

    def find_by_token(self, raw_token: str) -> Optional[Invite]:
        with transaction() as conn:
            r = conn.execute(select(t).where(t.c.token_hash == _hash(raw_token))).first()
        return _row(r) if r else None

    def mark_accepted(self, invite: Invite, user_id: str) -> None:
        now = now_utc()
        with transaction() as conn:
            res = conn.execute(
                update(t).where(and_(t.c.invite_id == invite.invite_id, t.c.accepted_at.is_(None),
                                     t.c.revoked_at.is_(None)))
                .values(accepted_by=user_id, accepted_at=now)
            )
        if res.rowcount != 1:
            raise ValueError("Invite was already used or revoked.")
        invite.accepted_by, invite.accepted_at = user_id, to_iso(now)

    def revoke(self, invite_id: str, org_id: str) -> Optional[Invite]:
        with transaction() as conn:
            conn.execute(update(t).where(and_(t.c.invite_id == invite_id, t.c.org_id == org_id,
                                              t.c.revoked_at.is_(None))).values(revoked_at=now_utc()))
            r = conn.execute(select(t).where(and_(t.c.invite_id == invite_id, t.c.org_id == org_id))).first()
        return _row(r) if r else None

    def list_by_org(self, org_id: str) -> List[Invite]:
        with transaction() as conn:
            rows = conn.execute(select(t).where(t.c.org_id == org_id).order_by(t.c.created_at)).all()
        return [_row(r) for r in rows]

    def remove_org(self, org_id: str) -> None:
        """Revoke every pending invite (rows are kept for history)."""
        with transaction() as conn:
            conn.execute(update(t).where(and_(t.c.org_id == org_id, t.c.revoked_at.is_(None),
                                              t.c.accepted_at.is_(None))).values(revoked_at=now_utc()))

    def _clear(self) -> None:  # pragma: no cover
        pass

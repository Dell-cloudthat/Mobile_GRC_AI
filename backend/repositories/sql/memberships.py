"""Postgres: org memberships (additive roles, expiry enforced on every read used for authz)."""

from __future__ import annotations

from typing import List, Optional, Set

from sqlalchemy import and_, delete, or_, select

import backend.repositories.org_membership_repo as membership_module
from backend.db import transaction
from backend.db.schema import org_memberships as m
from backend.repositories.org_membership_repo import (
    ROLES_REQUIRING_EXPIRY,
    VALID_ROLES,
    OrgMembership,
)
from backend.repositories.sql._util import to_dt, to_iso


def _now():
    # Read through the module so tests can move the clock (monkeypatch utcnow).
    return membership_module.utcnow()


def _active(now):
    return or_(m.c.expires_at.is_(None), m.c.expires_at > now)


def _row(r) -> OrgMembership:
    return OrgMembership(
        user_id=r.user_id, org_id=r.org_id, role=r.role, granted_by=r.granted_by,
        granted_at=to_iso(r.granted_at), expires_at=to_iso(r.expires_at),
    )


class SqlOrgMembershipRepository:
    def active_roles(self, user_id: str, org_id: str) -> Set[str]:
        with transaction() as conn:
            rows = conn.execute(
                select(m.c.role).where(and_(m.c.user_id == user_id, m.c.org_id == org_id, _active(_now())))
            ).all()
        return {r.role for r in rows}

    def has_any_active(self, user_id: str, org_id: str) -> bool:
        return bool(self.active_roles(user_id, org_id))

    def get_role(self, user_id: str, org_id: str, role: str) -> Optional[OrgMembership]:
        with transaction() as conn:
            r = conn.execute(select(m).where(and_(
                m.c.user_id == user_id, m.c.org_id == org_id, m.c.role == role, _active(_now())
            ))).first()
        return _row(r) if r else None

    def list_by_org(self, org_id: str, *, include_expired: bool = False) -> List[OrgMembership]:
        q = select(m).where(m.c.org_id == org_id)
        if not include_expired:
            q = q.where(_active(_now()))
        with transaction() as conn:
            rows = conn.execute(q.order_by(m.c.user_id, m.c.role)).all()
        return [_row(r) for r in rows]

    def list_by_user(self, user_id: str, *, include_expired: bool = False) -> List[OrgMembership]:
        q = select(m).where(m.c.user_id == user_id)
        if not include_expired:
            q = q.where(_active(_now()))
        with transaction() as conn:
            rows = conn.execute(q.order_by(m.c.org_id, m.c.role)).all()
        return [_row(r) for r in rows]

    def users_with_role(self, org_id: str, role: str) -> List[str]:
        return [x.user_id for x in self.list_by_org(org_id) if x.role == role]

    def add(self, membership: OrgMembership) -> None:
        if membership.role not in VALID_ROLES:
            raise ValueError(f"Invalid role '{membership.role}'. Must be one of {sorted(VALID_ROLES)}.")
        if membership.role in ROLES_REQUIRING_EXPIRY and not membership.expires_at:
            raise ValueError(f"Role '{membership.role}' requires an expires_at date.")
        key = and_(m.c.user_id == membership.user_id, m.c.org_id == membership.org_id,
                   m.c.role == membership.role)
        with transaction() as conn:
            existing = conn.execute(select(m).where(key).with_for_update()).first()
            if existing is not None:
                if existing.expires_at is None or existing.expires_at > _now():
                    raise KeyError(
                        f"User '{membership.user_id}' already holds role '{membership.role}' "
                        f"in org '{membership.org_id}'."
                    )
                conn.execute(delete(m).where(key))  # replace an expired grant
            conn.execute(m.insert().values(
                user_id=membership.user_id, org_id=membership.org_id, role=membership.role,
                granted_by=membership.granted_by, granted_at=to_dt(membership.granted_at),
                expires_at=to_dt(membership.expires_at),
            ))

    def remove_role(self, user_id: str, org_id: str, role: str) -> bool:
        with transaction() as conn:
            res = conn.execute(delete(m).where(and_(m.c.user_id == user_id, m.c.org_id == org_id, m.c.role == role)))
        return res.rowcount > 0

    def remove_all(self, user_id: str, org_id: str) -> int:
        with transaction() as conn:
            return conn.execute(delete(m).where(and_(m.c.user_id == user_id, m.c.org_id == org_id))).rowcount

    def remove_org(self, org_id: str) -> int:
        with transaction() as conn:
            return conn.execute(delete(m).where(m.c.org_id == org_id)).rowcount

    def _clear(self) -> None:  # pragma: no cover
        pass

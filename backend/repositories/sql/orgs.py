"""Postgres: organizations (soft delete) and users."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import and_, select, update

from backend.db import transaction
from backend.db.schema import organizations
from backend.repositories.org_repo import Organization, new_org_id
from backend.repositories.sql._util import now_utc, to_iso


def _row_to_org(r) -> Organization:
    return Organization(
        org_id=r.org_id,
        name=r.name,
        created_by=r.created_by,
        created_at=to_iso(r.created_at),
        updated_at=to_iso(r.updated_at),
        msp_id=r.msp_id,
        contact_email=r.contact_email,
        notes=r.notes,
        profile=dict(r.profile or {}),
    )


_LIVE = organizations.c.deleted_at.is_(None)


class SqlOrgRepository:
    def create(self, *, name: str, created_by: str, msp_id: Optional[str] = None,
               profile: Optional[Dict[str, Any]] = None, contact_email: Optional[str] = None,
               notes: Optional[str] = None) -> Organization:
        now = now_utc()
        values = dict(
            org_id=new_org_id(), name=name, created_by=created_by, created_at=now, updated_at=now,
            msp_id=msp_id, contact_email=contact_email, notes=notes,
            profile={"business_name": name, **(profile or {})},
        )
        with transaction() as conn:
            conn.execute(organizations.insert().values(**values))
        return self.get(values["org_id"])

    def get(self, org_id: str) -> Optional[Organization]:
        with transaction() as conn:
            r = conn.execute(select(organizations).where(and_(organizations.c.org_id == org_id, _LIVE))).first()
        return _row_to_org(r) if r else None

    def list_by_msp(self, msp_id: str) -> List[Organization]:
        with transaction() as conn:
            rows = conn.execute(
                select(organizations).where(and_(organizations.c.msp_id == msp_id, _LIVE))
                .order_by(organizations.c.created_at)
            ).all()
        return [_row_to_org(r) for r in rows]

    def update_profile(self, org_id: str, profile: Dict[str, Any]) -> Organization:
        with transaction() as conn:
            r = conn.execute(
                select(organizations).where(and_(organizations.c.org_id == org_id, _LIVE)).with_for_update()
            ).first()
            if r is None:
                raise KeyError(org_id)
            merged = {**(r.profile or {}), **profile}
            values: Dict[str, Any] = {"profile": merged, "updated_at": now_utc()}
            if profile.get("business_name"):
                values["name"] = profile["business_name"]
            conn.execute(update(organizations).where(organizations.c.org_id == org_id).values(**values))
        return self.get(org_id)

    def update_fields(self, org_id: str, **fields: Any) -> Organization:
        allowed = {"contact_email", "notes"}
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"Fields {sorted(bad)} cannot be updated.")
        with transaction() as conn:
            conn.execute(update(organizations).where(and_(organizations.c.org_id == org_id, _LIVE))
                         .values(**fields, updated_at=now_utc()))
        return self.get(org_id)

    def delete(self, org_id: str) -> None:
        """Soft delete: the org becomes unreachable; its history is retained."""
        with transaction() as conn:
            conn.execute(update(organizations).where(and_(organizations.c.org_id == org_id, _LIVE))
                         .values(deleted_at=now_utc(), updated_at=now_utc()))

    def _clear(self) -> None:  # pragma: no cover - test helper; schema is reset per test run instead
        pass

"""Postgres: AI app observations (current state) + decisions (append-only)."""

from __future__ import annotations

from typing import Dict, List, Optional

from sqlalchemy import and_, delete, select, text
from sqlalchemy.dialects.postgresql import insert

from backend.ai_governance.observations import merge
from backend.db import transaction
from backend.db.schema import ai_app_decisions as dc
from backend.db.schema import ai_app_observations as ob
from backend.repositories.sql._util import now_utc, to_dt, to_iso

_OBS_COLUMNS = ("display_name", "listed", "sources", "users", "reported_user_count", "scopes",
                "consent_types", "domains", "raw_names", "first_seen", "last_seen", "updated_at")


def _obs(r) -> Dict:
    o = {
        "app_key": r.app_key, "display_name": r.display_name, "listed": r.listed,
        "sources": list(r.sources), "users": list(r.users or []),
        "reported_user_count": r.reported_user_count, "scopes": list(r.scopes),
        "consent_types": list(r.consent_types), "domains": list(r.domains), "raw_names": list(r.raw_names),
        "first_seen": to_iso(r.first_seen), "last_seen": to_iso(r.last_seen), "updated_at": to_iso(r.updated_at),
    }
    o["user_count"] = max(len(o["users"]), o["reported_user_count"])
    return o


def _decision(r) -> Dict:
    return {
        "decision_id": r.decision_id, "app_key": r.app_key, "decision": r.decision, "note": r.note,
        "expires_at": to_iso(r.expires_at), "decided_by_user_id": r.decided_by_user_id,
        "decided_by_name": r.decided_by_name, "decided_at": to_iso(r.decided_at),
    }


class SqlAiUsageRepository:
    def merge_observations(self, org_id: str, incoming: List[Dict]) -> int:
        now = to_iso(now_utc())
        keys = [o["app_key"] for o in incoming]
        with transaction() as conn:
            # One import per org at a time, so two concurrent imports can't each
            # merge from the same old row and drop the other's users.
            conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"ai_obs:{org_id}"})
            existing = {
                r.app_key: _obs(r)
                for r in conn.execute(
                    select(ob).where(and_(ob.c.org_id == org_id, ob.c.app_key.in_(keys)))
                ).all()
            }
            for o in incoming:
                m = merge(existing.get(o["app_key"]), o, updated_at=now)
                values = {
                    "org_id": org_id, "app_key": m["app_key"], "display_name": m["display_name"][:200],
                    "listed": m["listed"], "sources": m["sources"], "users": m["users"],
                    "reported_user_count": m["reported_user_count"], "scopes": m["scopes"],
                    "consent_types": m["consent_types"], "domains": m["domains"], "raw_names": m["raw_names"],
                    "first_seen": to_dt(m["first_seen"]), "last_seen": to_dt(m["last_seen"]),
                    "updated_at": to_dt(now),
                }
                stmt = insert(ob).values(**values)
                stmt = stmt.on_conflict_do_update(
                    index_elements=[ob.c.org_id, ob.c.app_key],
                    set_={c: stmt.excluded[c] for c in _OBS_COLUMNS},
                )
                conn.execute(stmt)
        return len(incoming)

    def list_observations(self, org_id: str) -> List[Dict]:
        with transaction() as conn:
            rows = conn.execute(select(ob).where(ob.c.org_id == org_id)).all()
        return [_obs(r) for r in rows]

    def get_observation(self, org_id: str, app_key: str) -> Optional[Dict]:
        with transaction() as conn:
            r = conn.execute(select(ob).where(and_(ob.c.org_id == org_id, ob.c.app_key == app_key))).first()
        return _obs(r) if r else None

    def add_decision(self, org_id: str, record: Dict) -> Dict:
        with transaction() as conn:
            conn.execute(dc.insert().values(
                decision_id=record["decision_id"], org_id=org_id, app_key=record["app_key"],
                decision=record["decision"], note=record.get("note"), expires_at=to_dt(record.get("expires_at")),
                decided_by_user_id=record["decided_by_user_id"], decided_by_name=record["decided_by_name"],
                decided_at=to_dt(record["decided_at"]),
            ))
        return dict(record)

    def list_decisions(self, org_id: str) -> List[Dict]:
        with transaction() as conn:
            rows = conn.execute(select(dc).where(dc.c.org_id == org_id).order_by(dc.c.seq)).all()
        return [_decision(r) for r in rows]

    def remove_org(self, org_id: str) -> None:
        with transaction() as conn:
            conn.execute(delete(ob).where(ob.c.org_id == org_id))

    def _clear(self) -> None:  # pragma: no cover
        pass

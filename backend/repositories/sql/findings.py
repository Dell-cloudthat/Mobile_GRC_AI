"""Postgres: findings (current-state projection) + finding_events (append-only)."""

from __future__ import annotations

import uuid
from typing import Dict, List, Optional

from sqlalchemy import and_, select, update

from backend.db import transaction
from backend.db.schema import finding_events as ev
from backend.db.schema import findings as f
from backend.repositories.finding_repo import (
    TRANSITIONS,
    Finding,
    FindingEvent,
    InMemoryFindingRepository,
)
from backend.repositories.sql._util import now_utc, to_dt, to_iso


def _event(r) -> FindingEvent:
    return FindingEvent(
        event_id=r.event_id, finding_id=r.finding_id, action=r.action, from_state=r.from_state,
        to_state=r.to_state, actor_user_id=r.actor_user_id, actor_name=r.actor_name,
        occurred_at=to_iso(r.occurred_at), note=r.note,
    )


def _finding(r, events: List[FindingEvent]) -> Finding:
    return Finding(
        finding_id=r.finding_id, org_id=r.org_id, title=r.title, description=r.description,
        severity=r.severity, control_ids=list(r.control_ids), state=r.state,
        created_by_user_id=r.created_by_user_id, created_at=to_iso(r.created_at),
        updated_at=to_iso(r.updated_at), assigned_to_user_id=r.assigned_to_user_id, events=events,
        risk_accepted_until=to_iso(r.risk_accepted_until), risk_justification=r.risk_justification,
        risk_accepted_by=r.risk_accepted_by,
    )


def _events_for(conn, finding_ids: List[str]) -> Dict[str, List[FindingEvent]]:
    out: Dict[str, List[FindingEvent]] = {fid: [] for fid in finding_ids}
    if not finding_ids:
        return out
    rows = conn.execute(select(ev).where(ev.c.finding_id.in_(finding_ids)).order_by(ev.c.seq)).all()
    for r in rows:
        out[r.finding_id].append(_event(r))
    return out


class SqlFindingRepository:
    # Separation-of-duties helpers only read finding.events — reuse them verbatim.
    last_remediator = InMemoryFindingRepository.last_remediator
    remediators = InMemoryFindingRepository.remediators

    def create(self, *, org_id: str, title: str, description: str, severity: str,
               control_ids: List[str], created_by_user_id: str, created_by_name: str) -> Finding:
        now = now_utc()
        fid = str(uuid.uuid4())
        with transaction() as conn:
            conn.execute(f.insert().values(
                finding_id=fid, org_id=org_id, title=title, description=description, severity=severity,
                control_ids=list(control_ids), state="open", created_by_user_id=created_by_user_id,
                created_at=now, updated_at=now,
            ))
            conn.execute(ev.insert().values(
                event_id=str(uuid.uuid4()), finding_id=fid, org_id=org_id, action="create",
                from_state="", to_state="open", actor_user_id=created_by_user_id,
                actor_name=created_by_name, occurred_at=now,
            ))
        return self.get(fid, org_id)

    def get(self, finding_id: str, org_id: str) -> Optional[Finding]:
        with transaction() as conn:
            r = conn.execute(select(f).where(and_(f.c.finding_id == finding_id, f.c.org_id == org_id))).first()
            if r is None:
                return None
            return _finding(r, _events_for(conn, [finding_id])[finding_id])

    def list_by_org(self, org_id: str) -> List[Finding]:
        with transaction() as conn:
            rows = conn.execute(select(f).where(f.c.org_id == org_id).order_by(f.c.created_at)).all()
            events = _events_for(conn, [r.finding_id for r in rows])
        return [_finding(r, events[r.finding_id]) for r in rows]

    def list_by_control(self, org_id: str, control_id: str) -> List[Finding]:
        with transaction() as conn:
            rows = conn.execute(select(f).where(and_(f.c.org_id == org_id, f.c.control_ids.any(control_id)))).all()
            events = _events_for(conn, [r.finding_id for r in rows])
        return [_finding(r, events[r.finding_id]) for r in rows]

    def transition(self, finding: Finding, *, action: str, actor_user_id: str, actor_name: str,
                   note: Optional[str] = None, assigned_to_user_id: Optional[str] = None,
                   risk_accepted_until: Optional[str] = None,
                   risk_justification: Optional[str] = None) -> FindingEvent:
        now = now_utc()
        with transaction() as conn:
            # Lock the row and validate against the CURRENT state, not the caller's copy.
            row = conn.execute(select(f).where(f.c.finding_id == finding.finding_id).with_for_update()).one()
            allowed = TRANSITIONS.get(row.state, {})
            if action not in allowed:
                raise ValueError(
                    f"Action '{action}' is not allowed from state '{row.state}'. "
                    f"Allowed actions: {sorted(allowed.keys()) or 'none'}."
                )
            to_state = allowed[action]
            values = {"state": to_state, "updated_at": now}
            if assigned_to_user_id is not None:
                values["assigned_to_user_id"] = assigned_to_user_id
            elif action == "start" and not row.assigned_to_user_id:
                values["assigned_to_user_id"] = actor_user_id
            if action == "risk_accept":
                values.update(risk_accepted_until=to_dt(risk_accepted_until),
                              risk_justification=risk_justification, risk_accepted_by=actor_user_id)
            elif action == "reopen":
                values.update(risk_accepted_until=None, risk_justification=None, risk_accepted_by=None)
            conn.execute(update(f).where(f.c.finding_id == finding.finding_id).values(**values))
            event_id = str(uuid.uuid4())
            conn.execute(ev.insert().values(
                event_id=event_id, finding_id=finding.finding_id, org_id=finding.org_id, action=action,
                from_state=row.state, to_state=to_state, actor_user_id=actor_user_id,
                actor_name=actor_name, occurred_at=now, note=note,
            ))

        fresh = self.get(finding.finding_id, finding.org_id)
        # Keep the caller's object in sync so it can be serialized directly.
        finding.__dict__.update(fresh.__dict__)
        return next(e for e in finding.events if e.event_id == event_id)

    def remove_org(self, org_id: str) -> None:
        """No-op: findings and their event history are retained when an org is deleted."""

    def _clear(self) -> None:  # pragma: no cover
        pass

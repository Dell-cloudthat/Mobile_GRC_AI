"""
SecurityOS Findings API — Phase 2

Manages security findings and their state-machine lifecycle.

Routes:
  POST   /api/v1/securityos/organizations/{org_id}/findings
  GET    /api/v1/securityos/organizations/{org_id}/findings
  GET    /api/v1/securityos/organizations/{org_id}/findings/{finding_id}
  POST   /api/v1/securityos/organizations/{org_id}/findings/{finding_id}/transition

Security invariants:
  - Server sets all timestamps and actor fields.
  - Self-approval prohibition: the user who submitted a finding for review
    cannot be the same user who approves/closes it (→ 409).
  - Append-only audit trail: events are never deleted.
  - Tenant isolation: require_org_access() on every route.
"""

from datetime import timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from backend.api.api import CONTROLS_BY_ID
from backend.api.orgs import validate_future_iso
from backend.auth.context import Principal, get_principal, require_org_access
from backend.auth.permissions import (
    PERM_FINDING_APPROVE_CLOSE,
    PERM_FINDING_ASSIGN,
    PERM_FINDING_REMEDIATE,
    PERM_FINDING_VIEW,
    PERM_RISK_ACCEPT,
    effective_permissions,
    permissions_for_roles,
    require_any_permission,
    require_permission,
)
from backend.repositories.finding_repo import TRANSITIONS, finding_repo
from backend.repositories.org_membership_repo import org_membership_repo, parse_iso, utcnow

router = APIRouter(prefix="/api/v1/securityos", tags=["Findings"])

VALID_SEVERITIES = frozenset({"critical", "high", "medium", "low", "info"})

# Severities whose closure needs an independent executive approval.
HIGH_RISK_SEVERITIES = frozenset({"critical", "high"})

# Risk acceptance limits.
RISK_ACCEPT_MAX_DAYS = 365
RISK_ACCEPT_MAX_DAYS_CRITICAL = 90
RISK_JUSTIFICATION_MIN_CHARS = 20

# Map action → required permission.  "approve" on Low/Medium/Info has an extra
# path (the submitting remediator may close it) handled in transition_finding.
ACTION_PERMISSIONS = {
    "assign":      PERM_FINDING_ASSIGN,
    "start":       PERM_FINDING_REMEDIATE,
    "submit":      PERM_FINDING_REMEDIATE,
    "approve":     PERM_FINDING_APPROVE_CLOSE,
    "reject":      PERM_FINDING_APPROVE_CLOSE,
    "reopen":      PERM_FINDING_APPROVE_CLOSE,
    "risk_accept": PERM_RISK_ACCEPT,
}


# ── Pydantic models ───────────────────────────────────────────────────────────

class FindingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., min_length=1, max_length=300)
    description: str = Field(..., min_length=1, max_length=5000)
    severity: str = Field(..., description=f"One of: {sorted(VALID_SEVERITIES)}")
    control_ids: List[str] = Field(default_factory=list)


class FindingTransition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str = Field(..., description="State-machine action to apply")
    note: Optional[str] = Field(None, max_length=2000)
    assigned_to_user_id: Optional[str] = Field(
        None, description="Required when action='assign'"
    )
    expires_at: Optional[str] = Field(
        None, description="Required when action='risk_accept' (ISO-8601, ≤365 days; ≤90 for critical)"
    )
    justification: Optional[str] = Field(
        None, max_length=2000, description="Required when action='risk_accept' (≥20 chars)"
    )


# ── Serialization ─────────────────────────────────────────────────────────────

def _serialize_event(e) -> dict:
    return {
        "event_id": e.event_id,
        "action": e.action,
        "from_state": e.from_state,
        "to_state": e.to_state,
        "actor_user_id": e.actor_user_id,
        "actor_name": e.actor_name,
        "occurred_at": e.occurred_at,
        "note": e.note,
    }


def _serialize_finding(f, *, include_events: bool = False) -> dict:
    d: dict = {
        "finding_id": f.finding_id,
        "org_id": f.org_id,
        "title": f.title,
        "description": f.description,
        "severity": f.severity,
        "control_ids": f.control_ids,
        "state": f.state,
        "created_by_user_id": f.created_by_user_id,
        "assigned_to_user_id": f.assigned_to_user_id,
        "created_at": f.created_at,
        "updated_at": f.updated_at,
        "risk_accepted_until": f.risk_accepted_until,
        "risk_justification": f.risk_justification,
        "risk_accepted_by": f.risk_accepted_by,
        "risk_acceptance_expired": f.risk_acceptance_expired(),
    }
    if include_events:
        d["events"] = [_serialize_event(e) for e in f.events]
    d["remediated_by"] = sorted(finding_repo.remediators(f))
    d["last_submitted_by"] = finding_repo.last_remediator(f)
    return d


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post(
    "/organizations/{org_id}/findings",
    status_code=201,
    summary="Create a new finding",
)
def create_finding(
    org_id: str,
    payload: FindingCreate,
    principal: Principal = Depends(get_principal),
):
    """
    Create a new finding in state 'open'.

    Actor identity and timestamps are set by the server.
    Anyone who can triage (finding.assign) or do the work (finding.remediate)
    may log a finding.  Opening a finding can only lower the score.
    """
    require_org_access(principal, org_id)
    require_any_permission(principal, org_id, PERM_FINDING_ASSIGN, PERM_FINDING_REMEDIATE)

    unknown = [c for c in payload.control_ids if c not in CONTROLS_BY_ID]
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown control_ids: {unknown}.")

    if payload.severity not in VALID_SEVERITIES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid severity '{payload.severity}'. Must be one of {sorted(VALID_SEVERITIES)}.",
        )

    finding = finding_repo.create(
        org_id=org_id,
        title=payload.title,
        description=payload.description,
        severity=payload.severity,
        control_ids=payload.control_ids,
        created_by_user_id=principal.user_id,
        created_by_name=principal.display_name,
    )
    return {"finding": _serialize_finding(finding, include_events=True)}


@router.get(
    "/organizations/{org_id}/findings",
    summary="List findings for an org",
)
def list_findings(
    org_id: str,
    state: Optional[str] = None,
    control_id: Optional[str] = None,
    principal: Principal = Depends(get_principal),
):
    """Return findings for the org, optionally filtered by state and/or control_id."""
    require_org_access(principal, org_id)
    require_permission(principal, org_id, PERM_FINDING_VIEW)

    findings = (finding_repo.list_by_control(org_id, control_id) if control_id
                else finding_repo.list_by_org(org_id))
    if state:
        findings = [f for f in findings if f.state == state]

    return {
        "org_id": org_id,
        "findings": [_serialize_finding(f) for f in findings],
        "total": len(findings),
    }


@router.get(
    "/organizations/{org_id}/findings/{finding_id}",
    summary="Get one finding with full event history",
)
def get_finding(
    org_id: str,
    finding_id: str,
    principal: Principal = Depends(get_principal),
):
    """Return a single finding with its full audit-event trail."""
    require_org_access(principal, org_id)
    require_permission(principal, org_id, PERM_FINDING_VIEW)

    finding = finding_repo.get(finding_id, org_id)
    if finding is None:
        raise HTTPException(status_code=404, detail=f"Finding '{finding_id}' not found.")

    return {"finding": _serialize_finding(finding, include_events=True)}


@router.post(
    "/organizations/{org_id}/findings/{finding_id}/transition",
    summary="Apply a state-machine transition to a finding",
)
def transition_finding(
    org_id: str,
    finding_id: str,
    payload: FindingTransition,
    principal: Principal = Depends(get_principal),
):
    """
    Apply a state transition (assign / start / submit / approve / reject / reopen / risk_accept).

    Self-approval prohibition: the same user who submitted a finding for review
    (action='submit') cannot also approve/close it (action='approve').
    Violation → 409.
    """
    require_org_access(principal, org_id)

    action = payload.action
    perm = ACTION_PERMISSIONS.get(action)
    if perm is None:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown action '{action}'. Valid actions: {sorted(ACTION_PERMISSIONS.keys())}.",
        )

    finding = finding_repo.get(finding_id, org_id)
    if finding is None:
        raise HTTPException(status_code=404, detail=f"Finding '{finding_id}' not found.")

    perms = effective_permissions(principal, org_id)
    if PERM_FINDING_VIEW not in perms:
        raise HTTPException(status_code=403, detail="Permission 'finding.view' is required.")

    if action == "approve":
        _check_approve(finding, principal, perms)
    else:
        require_permission(principal, org_id, perm)

    if action == "assign":
        _check_assignee(org_id, payload.assigned_to_user_id)

    risk_until = None
    if action == "risk_accept":
        risk_until = _check_risk_acceptance(finding, payload)

    try:
        event = finding_repo.transition(
            finding,
            action=action,
            actor_user_id=principal.user_id,
            actor_name=principal.display_name,
            note=payload.note,
            assigned_to_user_id=payload.assigned_to_user_id,
            risk_accepted_until=risk_until,
            risk_justification=payload.justification if action == "risk_accept" else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return {
        "finding": _serialize_finding(finding, include_events=True),
        "event": _serialize_event(event),
    }


# ── Transition guards ─────────────────────────────────────────────────────────

def _check_approve(finding, principal: Principal, perms: set) -> None:
    """
    High/Critical: requires finding.approve_close AND the approver did none of
    the remediation work.  Low/Medium/Info: an executive may approve, or the
    remediator who submitted it may close it themselves.
    """
    remediators = finding_repo.remediators(finding)

    if finding.severity in HIGH_RISK_SEVERITIES:
        if PERM_FINDING_APPROVE_CLOSE not in perms:
            raise HTTPException(
                status_code=403,
                detail=f"Closing a {finding.severity} finding requires 'finding.approve_close'.",
            )
        if principal.user_id in remediators:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Self-approval prohibited: you did remediation work on this "
                    f"{finding.severity} finding and cannot also approve it."
                ),
            )
        return

    if PERM_FINDING_APPROVE_CLOSE in perms:
        return
    if PERM_FINDING_REMEDIATE in perms and finding_repo.last_remediator(finding) == principal.user_id:
        return
    raise HTTPException(
        status_code=403,
        detail="Only an executive or the remediator who submitted this finding may close it.",
    )


def _check_assignee(org_id: str, assignee: Optional[str]) -> None:
    if not assignee:
        raise HTTPException(status_code=422, detail="'assigned_to_user_id' is required when action='assign'.")
    roles = org_membership_repo.active_roles(assignee, org_id)
    if PERM_FINDING_REMEDIATE not in permissions_for_roles(roles):
        raise HTTPException(
            status_code=422,
            detail="Assignee must be an active member who can remediate (engineer or MSP technician).",
        )


def _check_risk_acceptance(finding, payload: FindingTransition) -> str:
    if not payload.justification or len(payload.justification.strip()) < RISK_JUSTIFICATION_MIN_CHARS:
        raise HTTPException(
            status_code=422,
            detail=f"Risk acceptance requires a justification of at least {RISK_JUSTIFICATION_MIN_CHARS} characters.",
        )
    if not payload.expires_at:
        raise HTTPException(status_code=422, detail="Risk acceptance requires expires_at.")
    until = validate_future_iso(payload.expires_at, "expires_at")
    max_days = RISK_ACCEPT_MAX_DAYS_CRITICAL if finding.severity == "critical" else RISK_ACCEPT_MAX_DAYS
    if parse_iso(until) > utcnow() + timedelta(days=max_days):
        raise HTTPException(
            status_code=422,
            detail=f"Risk acceptance for a {finding.severity} finding may last at most {max_days} days.",
        )
    return until

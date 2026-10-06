"""
SecurityOS MSP (Managed Service Provider) API

MSPs manage multiple client organizations under a single account.
This router provides the MSP portal backend:

  POST   /api/v1/securityos/msp/{msp_id}/orgs              — create managed org
  GET    /api/v1/securityos/msp/{msp_id}/orgs              — list all managed orgs
  GET    /api/v1/securityos/msp/{msp_id}/orgs/{org_id}     — get one managed org
  DELETE /api/v1/securityos/msp/{msp_id}/orgs/{org_id}     — remove managed org
  GET    /api/v1/securityos/msp/{msp_id}/orgs/{org_id}/score  — get org score
  GET    /api/v1/securityos/msp/{msp_id}/dashboard         — aggregate dashboard

Authentication: every route requires a valid Bearer JWT.
Tenant isolation (Phase 2.1):
  - the caller's msp_id from the JWT must match the path msp_id, AND
  - the org must have been provisioned under that MSP, AND
  - the caller must hold an active membership in that client org.
  Any miss → 404.  Missing permission → 403.

The MSP staff member who provisions a client org becomes its admin and
msp_technician.  They can invite the client's executive, but MSP staff can
never hold the executive role in a client org, so the client always signs off.

Storage: shares org_repo / manual_status_repo / attestation_repo with /organizations,
so a client org has exactly one profile and one control state.
"""

from datetime import datetime
from typing import Dict, List, Optional, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from backend.api.api import apply_manual_status
from backend.api.orgs import grant_role
from backend.auth.context import Principal, get_principal, require_msp_access
from backend.auth.permissions import (
    PERM_FINDING_REMEDIATE,
    PERM_FINDING_VIEW,
    PERM_ORG_MANAGE,
    has_permission,
    require_permission,
)
from backend.controls.state import effective_statuses
from backend.repositories import control_state_repo
from backend.repositories.audit_repo import audit_repo
from backend.repositories.finding_repo import finding_repo
from backend.repositories.invite_repo import invite_repo
from backend.repositories.msp_org_repo import msp_org_repo
from backend.repositories.org_membership_repo import org_membership_repo
from backend.repositories.org_repo import Organization, org_repo
from backend.scoring.engine import calculate_score, ControlStatus

router = APIRouter(prefix="/api/v1/securityos/msp", tags=["MSP"])


# ── Pydantic models ───────────────────────────────────────────────────────────

class ManagedOrgCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=200, description="Client organization name")
    industry: str = ""
    employee_count: str = ""
    email_provider: str = ""
    cloud_providers: List[str] = []
    sensitive_data: List[str] = []
    contact_email: Optional[str] = None
    notes: Optional[str] = None


class ManagedOrgUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(None, min_length=1, max_length=200)
    industry: Optional[str] = None
    employee_count: Optional[str] = None
    email_provider: Optional[str] = None
    cloud_providers: Optional[List[str]] = None
    sensitive_data: Optional[List[str]] = None
    contact_email: Optional[str] = None
    notes: Optional[str] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_msp_org(principal: Principal, msp_id: str, org_id: str, permission: str) -> Organization:
    """
    Resolve a client org for an MSP route.  404 unless the org belongs to this
    MSP AND the caller holds an active membership in it; 403 without `permission`.
    """
    require_msp_access(principal, msp_id)
    org = org_repo.get(org_id)
    if (
        org is None
        or org.msp_id != msp_id
        or not org_membership_repo.has_any_active(principal.user_id, org_id)
    ):
        raise HTTPException(
            status_code=404,
            detail=f"Managed org '{org_id}' not found under MSP '{msp_id}'",
        )
    require_permission(principal, org_id, permission)
    return org


def _visible_orgs(principal: Principal, msp_id: str) -> List[Organization]:
    """Client orgs under this MSP that the caller can view."""
    return [
        o for o in org_repo.list_by_msp(msp_id)
        if has_permission(principal, o.org_id, PERM_FINDING_VIEW)
    ]


def _org_dict(org: Organization) -> Dict:
    return {
        "org_id": org.org_id,
        "msp_id": org.msp_id,
        "name": org.name,
        "contact_email": org.contact_email,
        "notes": org.notes,
        "profile": dict(org.profile),
        "statuses": effective_statuses(org.org_id),
        "created_at": org.created_at,
        "updated_at": org.updated_at,
    }


def _score_org(org: Organization) -> Dict:
    result = calculate_score(effective_statuses(org.org_id), business_profile=org.profile)
    return {
        "total_score": result.total_score,
        "grade": result.grade,
        "color": result.color,
        "verified_pct": result.verified_pct,
        "summary": result.summary,
        "top_issues": [
            {
                "control_id": c.control_id,
                "name": c.name,
                "short_name": c.short_name,
                "severity": c.severity,
                "status": c.status,
                "customer_message": c.customer_message,
            }
            for c in result.top_issues
        ],
    }


def _risk_level(score: int) -> str:
    if score >= 80: return "low"
    if score >= 65: return "moderate"
    if score >= 45: return "high"
    return "critical"


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/{msp_id}/orgs", status_code=201, summary="Create a managed client org")
def create_managed_org(
    msp_id: str,
    payload: ManagedOrgCreate,
    principal: Principal = Depends(get_principal),
):
    """
    Create a new managed client organization under this MSP account.
    Returns the new org record including its generated org_id.
    """
    require_msp_access(principal, msp_id)

    org = org_repo.create(
        name=payload.name,
        created_by=principal.user_id,
        msp_id=msp_id,
        contact_email=payload.contact_email,
        notes=payload.notes,
        profile={
            "industry": payload.industry,
            "employee_count": payload.employee_count,
            "email_provider": payload.email_provider,
            "cloud_providers": payload.cloud_providers,
            "sensitive_data": payload.sensitive_data,
        },
    )
    msp_org_repo.add_org(msp_id, org.org_id)
    audit_repo.record(org_id=org.org_id, actor_user_id=principal.user_id, action="org.created",
                      via="msp_provisioning", msp_id=msp_id)
    # The provisioning technician administers the org and can work findings.
    # They can invite the client's executive but can never become one.
    for role in ("admin", "msp_technician"):
        grant_role(user_id=principal.user_id, org_id=org.org_id, role=role,
                   granted_by=principal.user_id, via="msp_provisioning")

    return {
        "org_id": org.org_id,
        "msp_id": msp_id,
        "name": org.name,
        "score": _score_org(org),
        "created_at": org.created_at,
        "your_roles": sorted(org_membership_repo.active_roles(principal.user_id, org.org_id)),
    }


@router.get("/{msp_id}/orgs", summary="List all managed client orgs")
def list_managed_orgs(
    msp_id: str,
    principal: Principal = Depends(get_principal),
):
    """
    Return all client organizations managed by this MSP, with their current scores.
    Sorted by score ascending (highest risk first) for the MSP dashboard.
    """
    require_msp_access(principal, msp_id)

    results = []
    for org in _visible_orgs(principal, msp_id):
        score = _score_org(org)
        results.append({
            "org_id": org.org_id,
            "name": org.name,
            "industry": org.profile.get("industry", ""),
            "contact_email": org.contact_email,
            "score": score["total_score"],
            "grade": score["grade"],
            "color": score["color"],
            "risk_level": _risk_level(score["total_score"]),
            "open_issues": score["summary"].get("failing", 0) + score["summary"].get("unknown", 0),
            "verified_pct": score["verified_pct"],
            "top_issue": score["top_issues"][0]["short_name"] if score["top_issues"] else None,
            "updated_at": org.updated_at,
        })

    # Sort: critical risk first, then high, then score ascending within group
    risk_order = {"critical": 0, "high": 1, "moderate": 2, "low": 3}
    results.sort(key=lambda x: (risk_order.get(x["risk_level"], 4), x["score"]))

    return {
        "msp_id": msp_id,
        "total_orgs": len(results),
        "orgs": results,
    }


@router.get("/{msp_id}/orgs/{org_id}", summary="Get one managed org")
def get_managed_org(
    msp_id: str,
    org_id: str,
    principal: Principal = Depends(get_principal),
):
    """Return full details for one managed client org including profile and current score."""
    org = _get_msp_org(principal, msp_id, org_id, PERM_FINDING_VIEW)
    return {**_org_dict(org), "current_score": _score_org(org)}


@router.patch("/{msp_id}/orgs/{org_id}", summary="Update a managed org's profile")
def update_managed_org(
    msp_id: str,
    org_id: str,
    payload: ManagedOrgUpdate,
    principal: Principal = Depends(get_principal),
):
    """Update name, industry, contact info, or other profile fields.  Requires org.manage."""
    org = _get_msp_org(principal, msp_id, org_id, PERM_ORG_MANAGE)

    profile_changes: Dict[str, Any] = {}
    if payload.name is not None:
        profile_changes["business_name"] = payload.name
    for field_name in ("industry", "employee_count", "email_provider", "cloud_providers", "sensitive_data"):
        value = getattr(payload, field_name)
        if value is not None:
            profile_changes[field_name] = value
    if profile_changes:
        org_repo.update_profile(org_id, profile_changes)
    field_changes = {k: getattr(payload, k) for k in ("contact_email", "notes") if getattr(payload, k) is not None}
    if field_changes:
        org_repo.update_fields(org_id, **field_changes)
    org = org_repo.get(org_id)
    audit_repo.record(org_id=org_id, actor_user_id=principal.user_id, action="org.profile_updated")
    return {"org_id": org_id, "updated": True, "org": _org_dict(org)}


@router.delete("/{msp_id}/orgs/{org_id}", status_code=204, summary="Remove a managed org")
def delete_managed_org(
    msp_id: str,
    org_id: str,
    principal: Principal = Depends(get_principal),
):
    """Remove a client organization and all of its data.  Requires org.manage."""
    _get_msp_org(principal, msp_id, org_id, PERM_ORG_MANAGE)
    audit_repo.record(org_id=org_id, actor_user_id=principal.user_id, action="org.deleted", msp_id=msp_id)
    msp_org_repo.remove_org(msp_id, org_id)
    org_membership_repo.remove_org(org_id)
    invite_repo.remove_org(org_id)
    finding_repo.remove_org(org_id)
    control_state_repo.remove_org(org_id)
    org_repo.delete(org_id)


@router.get("/{msp_id}/orgs/{org_id}/score", summary="Get score for a managed org")
def get_org_score(
    msp_id: str,
    org_id: str,
    principal: Principal = Depends(get_principal),
):
    """
    Calculate and return the Security Readiness Score for a managed client org.
    Identical to the standalone /score endpoint but scoped to MSP-managed orgs.
    """
    org = _get_msp_org(principal, msp_id, org_id, PERM_FINDING_VIEW)
    result = calculate_score(effective_statuses(org_id), business_profile=org.profile)

    return {
        "org_id": org_id,
        "msp_id": msp_id,
        "org_name": org.name,
        "total_score": result.total_score,
        "grade": result.grade,
        "color": result.color,
        "verified_pct": result.verified_pct,
        "confidence_note": result.confidence_note,
        "summary": result.summary,
        "categories": {
            cat_id: {
                "id": cat.id,
                "label": cat.label,
                "score": cat.score,
                "max_score": cat.max_score,
                "passing": cat.passing_count,
                "failing": cat.failing_count,
                "unknown": cat.unknown_count,
            }
            for cat_id, cat in result.categories.items()
        },
        "top_issues": [
            {
                "control_id": c.control_id,
                "name": c.name,
                "short_name": c.short_name,
                "severity": c.severity,
                "status": c.status,
                "customer_message": c.customer_message,
            }
            for c in result.top_issues
        ],
    }


@router.patch(
    "/{msp_id}/orgs/{org_id}/statuses/{control_id}",
    summary="Update a control status for a managed org",
)
def update_org_control_status(
    msp_id: str,
    org_id: str,
    control_id: str,
    status: str,
    notes: Optional[str] = None,
    evidence_source: str = "manual",
    principal: Principal = Depends(get_principal),
):
    """
    Record a manual status for a client control (fail / unknown / in_progress
    only).  Requires finding.remediate.  "pass" and "not_applicable" → 403: the
    MSP cannot mark its own work as passing; the client's executive approves it.
    """
    _get_msp_org(principal, msp_id, org_id, PERM_FINDING_REMEDIATE)
    try:
        ControlStatus(status)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status '{status}'. Valid: fail, unknown, in_progress",
        )
    # Manual input is always recorded as manual evidence, whatever the caller claims.
    entry = apply_manual_status(org_id, control_id, status, notes, principal)
    return {"org_id": org_id, "control_id": control_id, "status": entry["status"]}


@router.get("/{msp_id}/dashboard", summary="MSP aggregate dashboard")
def get_msp_dashboard(
    msp_id: str,
    principal: Principal = Depends(get_principal),
):
    """
    Aggregate view across all managed client orgs for the MSP portal.
    Returns portfolio-level risk metrics and per-org summary.
    """
    require_msp_access(principal, msp_id)

    orgs = _visible_orgs(principal, msp_id)

    if not orgs:
        return {
            "msp_id": msp_id,
            "total_orgs": 0,
            "portfolio_score": None,
            "risk_distribution": {"critical": 0, "high": 0, "moderate": 0, "low": 0},
            "orgs_at_risk": [],
            "common_issues": [],
            "orgs": [],
        }

    org_scores = []
    all_issues: Dict[str, int] = {}

    for org in orgs:
        score = _score_org(org)
        risk = _risk_level(score["total_score"])
        org_scores.append({
            "org_id": org.org_id,
            "name": org.name,
            "score": score["total_score"],
            "grade": score["grade"],
            "color": score["color"],
            "risk_level": risk,
            "open_issues": score["summary"].get("failing", 0) + score["summary"].get("unknown", 0),
            "top_issue": score["top_issues"][0]["short_name"] if score["top_issues"] else None,
        })
        for issue in score["top_issues"]:
            all_issues[issue["short_name"]] = all_issues.get(issue["short_name"], 0) + 1

    portfolio_score = int(sum(o["score"] for o in org_scores) / len(org_scores)) if org_scores else 0

    risk_dist: Dict[str, int] = {"critical": 0, "high": 0, "moderate": 0, "low": 0}
    for o in org_scores:
        risk_dist[o["risk_level"]] = risk_dist.get(o["risk_level"], 0) + 1

    orgs_at_risk = sorted(
        [o for o in org_scores if o["risk_level"] in ("critical", "high")],
        key=lambda x: x["score"],
    )

    common_issues = sorted(
        [{"name": k, "affected_orgs": v} for k, v in all_issues.items()],
        key=lambda x: -x["affected_orgs"],
    )[:5]

    risk_order = {"critical": 0, "high": 1, "moderate": 2, "low": 3}
    org_scores.sort(key=lambda x: (risk_order.get(x["risk_level"], 4), x["score"]))

    return {
        "msp_id": msp_id,
        "total_orgs": len(orgs),
        "portfolio_score": portfolio_score,
        "portfolio_grade": _portfolio_grade(portfolio_score),
        "risk_distribution": risk_dist,
        "orgs_at_risk": orgs_at_risk,
        "common_issues": common_issues,
        "orgs": org_scores,
        "generated_at": datetime.utcnow().isoformat(),
    }


def _portfolio_grade(score: int) -> str:
    if score >= 90: return "Excellent"
    if score >= 75: return "Good"
    if score >= 60: return "Fair"
    if score >= 40: return "Poor"
    return "At Risk"

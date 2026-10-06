"""
SecurityOS FastAPI router.
Handles business profiles, control status, scoring, and AI copilot.

Authentication: all /organizations/{org_id}/* routes require a Bearer JWT.
Public endpoints (no auth): GET /controls, GET /controls/{id}, POST /copilot.

Phase 2.1:
  - Every org route requires an active membership (404 otherwise) AND a
    permission (403 otherwise): reads need finding.view, profile writes need
    org.manage, status writes need finding.remediate.
  - Manual status writes may only set fail / unknown / in_progress.  A control
    reaches "pass" only through an approved finding or an active attestation
    (and, from Phase 5, integration evidence).  See backend/controls/state.py.
  - Score and Trust Passport are computed from that derived state.
"""
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

import json
from pathlib import Path

# Load catalog from the single source of truth
_CATALOG_PATH = Path(__file__).parent.parent.parent / "compliance" / "controls" / "catalog.json"
with open(_CATALOG_PATH) as _f:
    CONTROLS = json.load(_f)
CONTROLS_BY_ID = {c["id"]: c for c in CONTROLS}

from backend.auth.context import Principal, get_principal, require_org_access
from backend.auth.permissions import (
    PERM_FINDING_REMEDIATE,
    PERM_FINDING_VIEW,
    PERM_ORG_MANAGE,
    require_permission,
)
from backend.repositories.control_state_repo import manual_status_repo
from backend.repositories.audit_repo import audit_repo
from backend.repositories.org_repo import org_repo
from backend.scoring.engine import calculate_score, ControlStatus

router = APIRouter(prefix="/api/v1/securityos", tags=["SecurityOS"])


# ─── Pydantic Models ──────────────────────────────────────────────────────────

class BusinessProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    business_name: str = Field(..., min_length=1, max_length=200)
    industry: str = ""
    employee_count: str = ""
    revenue_range: str = ""
    cloud_providers: List[str] = []
    email_provider: str = ""
    sensitive_data: List[str] = []
    has_insurance: Optional[bool] = None
    regulatory_exposure: List[str] = []


class ControlStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    control_id: str
    status: ControlStatus
    notes: Optional[str] = None


class BulkControlStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    updates: List[ControlStatusUpdate]


class CopilotMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(..., min_length=1, max_length=2000)
    control_statuses: Optional[Dict[str, Dict]] = None
    profile: Optional[Dict] = None


# ─── Stores ───────────────────────────────────────────────────────────────────
# Profiles live on the Organization (org_repo); manual statuses live in
# manual_status_repo so the MSP router shares the same state.


def _effective_statuses(org_id: str) -> Dict[str, Dict]:
    # Imported lazily: backend.controls.state imports the finding repo, which is fine,
    # but keeping the import here avoids a cycle with routers that import this module.
    from backend.controls.state import effective_statuses
    return effective_statuses(org_id)


def _profile(org_id: str) -> Dict:
    org = org_repo.get(org_id)
    return dict(org.profile) if org else {}


def apply_manual_status(
    org_id: str,
    control_id: str,
    status: str,
    notes: Optional[str],
    principal: Principal,
    evidence_source: str = "manual",
) -> Dict:
    """Shared by /organizations and /msp status routes.  Rejects score-raising values."""
    from backend.controls.state import MANUAL_ALLOWED_STATUSES

    if control_id not in CONTROLS_BY_ID:
        raise HTTPException(status_code=404, detail=f"Control {control_id} not found")
    status_value = status.value if hasattr(status, "value") else str(status)
    if status_value not in MANUAL_ALLOWED_STATUSES:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Status '{status_value}' cannot be set manually. A control passes only when "
                "its finding is approved, it is covered by an active attestation, or an "
                "integration verifies it."
            ),
        )
    entry = {
        "status": status_value,
        "notes": notes,
        "evidence_source": evidence_source,
        "last_checked": datetime.utcnow().isoformat(),
        "set_by": principal.user_id,
    }
    manual_status_repo.set(org_id, control_id, entry)
    audit_repo.record(org_id=org_id, actor_user_id=principal.user_id, action="control.status_set",
                      control_id=control_id, status=status_value)
    return entry


# ─── Controls Catalog (public — no auth required) ────────────────────────────

VALID_CATEGORIES = {"identity", "devices", "data", "network", "organization", "ai_rmf"}


@router.get("/controls")
def list_controls(category: Optional[str] = None, framework: Optional[str] = None):
    """Return the full controls catalog, optionally filtered by category or framework."""
    controls = CONTROLS
    if category:
        if category not in VALID_CATEGORIES:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown category: {category}. Valid: {sorted(VALID_CATEGORIES)}",
            )
        controls = [c for c in controls if c["category"] == category]
    if framework:
        controls = [c for c in controls if framework in (c.get("framework_mappings") or {})]
    return {"controls": controls, "total": len(controls)}


@router.get("/controls/{control_id}")
def get_control(control_id: str):
    """Return a single control by ID."""
    control = CONTROLS_BY_ID.get(control_id)
    if not control:
        raise HTTPException(status_code=404, detail=f"Control {control_id} not found")
    return control


# ─── Business Profile ─────────────────────────────────────────────────────────

@router.post("/organizations/{org_id}/profile")
def update_profile(
    org_id: str,
    profile: BusinessProfile,
    principal: Principal = Depends(get_principal),
):
    """Create or update a business profile.  Requires org.manage."""
    require_org_access(principal, org_id)
    require_permission(principal, org_id, PERM_ORG_MANAGE)
    org = org_repo.update_profile(org_id, profile.model_dump())
    audit_repo.record(org_id=org_id, actor_user_id=principal.user_id, action="org.profile_updated")
    return {"org_id": org_id, "profile": {**org.profile, "updated_at": org.updated_at}}


@router.get("/organizations/{org_id}/profile")
def get_profile(
    org_id: str,
    principal: Principal = Depends(get_principal),
):
    """Retrieve a business profile.  Requires finding.view."""
    require_org_access(principal, org_id)
    require_permission(principal, org_id, PERM_FINDING_VIEW)
    org = org_repo.get(org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Profile not found")
    return {**org.profile, "updated_at": org.updated_at}


# ─── Control Statuses ─────────────────────────────────────────────────────────

@router.get("/organizations/{org_id}/statuses")
def get_control_statuses(
    org_id: str,
    principal: Principal = Depends(get_principal),
):
    """Effective control statuses (derived from findings, attestations, manual input)."""
    require_org_access(principal, org_id)
    require_permission(principal, org_id, PERM_FINDING_VIEW)
    return {"org_id": org_id, "statuses": _effective_statuses(org_id)}


@router.patch("/organizations/{org_id}/statuses")
def update_control_status(
    org_id: str,
    update: ControlStatusUpdate,
    principal: Principal = Depends(get_principal),
):
    """
    Record a manual status (fail / unknown / in_progress only).  Requires
    finding.remediate.  "pass" and "not_applicable" are rejected with 403.
    """
    require_org_access(principal, org_id)
    require_permission(principal, org_id, PERM_FINDING_REMEDIATE)
    entry = apply_manual_status(org_id, update.control_id, update.status, update.notes, principal)
    return {"control_id": update.control_id, "status": entry["status"]}


@router.put("/organizations/{org_id}/statuses/bulk")
def bulk_update_control_statuses(
    org_id: str,
    payload: BulkControlStatusUpdate,
    principal: Principal = Depends(get_principal),
):
    """
    Record several manual statuses.  All-or-nothing: if any entry is a
    score-raising value or an unknown control, nothing is written.
    """
    require_org_access(principal, org_id)
    require_permission(principal, org_id, PERM_FINDING_REMEDIATE)

    from backend.controls.state import MANUAL_ALLOWED_STATUSES
    for update in payload.updates:
        value = update.status.value if hasattr(update.status, "value") else str(update.status)
        if update.control_id not in CONTROLS_BY_ID:
            raise HTTPException(status_code=404, detail=f"Control {update.control_id} not found")
        if value not in MANUAL_ALLOWED_STATUSES:
            raise HTTPException(
                status_code=403,
                detail=f"Status '{value}' cannot be set manually (control {update.control_id}).",
            )

    results = []
    for update in payload.updates:
        entry = apply_manual_status(org_id, update.control_id, update.status, update.notes, principal)
        results.append({"control_id": update.control_id, "status": entry["status"]})
    return {"updated": len(results), "results": results}


# ─── Scoring ──────────────────────────────────────────────────────────────────

@router.get("/organizations/{org_id}/score")
def get_score(
    org_id: str,
    principal: Principal = Depends(get_principal),
):
    """Security Readiness Score, computed from derived control state."""
    require_org_access(principal, org_id)
    require_permission(principal, org_id, PERM_FINDING_VIEW)

    statuses = _effective_statuses(org_id)
    profile = _profile(org_id) or None
    result = calculate_score(statuses, business_profile=profile)
    return {
        "total_score": result.total_score,
        "max_score": result.max_score,
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


# ─── Trust Passport ───────────────────────────────────────────────────────────

@router.get("/organizations/{org_id}/passport")
def get_trust_passport(
    org_id: str,
    principal: Principal = Depends(get_principal),
):
    """Generate a Trust Passport, computed from derived control state."""
    require_org_access(principal, org_id)
    require_permission(principal, org_id, PERM_FINDING_VIEW)

    profile = _profile(org_id)
    statuses = _effective_statuses(org_id)
    score_data = calculate_score(statuses, business_profile=profile)

    KEY_PASSPORT_CONTROLS = [
        ("CTRL-ID-001", "Multi-Factor Authentication"),
        ("CTRL-DEV-001", "Device Encryption"),
        ("CTRL-DATA-003", "Data Backups"),
        ("CTRL-DEV-003", "Endpoint Protection"),
        ("CTRL-ORG-001", "Security Policy"),
        ("CTRL-ORG-002", "Incident Response"),
        ("CTRL-ORG-003", "Security Training"),
        ("CTRL-NET-004", "Admin Access Control"),
    ]

    control_summary = []
    for ctrl_id, label in KEY_PASSPORT_CONTROLS:
        entry = statuses.get(ctrl_id, {})
        control_summary.append({
            "control_id": ctrl_id,
            "label": label,
            "status": entry.get("status", ControlStatus.UNKNOWN),
            "last_checked": entry.get("last_checked"),
            "basis": entry.get("derived_from", "none"),
        })

    return {
        "org_id": org_id,
        "business_name": profile.get("business_name", ""),
        "industry": profile.get("industry", ""),
        "total_score": score_data.total_score,
        "grade": score_data.grade,
        "color": score_data.color,
        "category_scores": {
            cat_id: {"label": cat.label, "score": cat.score, "max_score": cat.max_score}
            for cat_id, cat in score_data.categories.items()
        },
        "key_controls": control_summary,
        "verified_at": datetime.utcnow().isoformat(),
        "summary": score_data.summary,
    }


# ─── AI Copilot (public — no auth required for context building) ─────────────

@router.post("/copilot")
def copilot_query(payload: CopilotMessage):
    """
    AI Security Copilot endpoint.
    Returns structured context for client-side AI processing.
    Authentication is optional here to allow unauthenticated copilot previews;
    for production deployments with sensitive org data, add get_principal dependency.
    """
    statuses = payload.control_statuses or {}
    profile = payload.profile or {}
    score_data = calculate_score(statuses, business_profile=profile)

    return {
        "context": {
            "score": score_data.total_score,
            "grade": score_data.grade,
            "open_issues": [
                {
                    "control_id": c.control_id,
                    "name": c.name,
                    "short_name": c.short_name,
                    "severity": c.severity,
                    "status": c.status,
                    "customer_message": c.customer_message,
                }
                for c in score_data.top_issues
            ],
            "profile_summary": {
                "industry": profile.get("industry", ""),
                "employee_count": profile.get("employee_count", ""),
                "sensitive_data": profile.get("sensitive_data", []),
            },
        },
        "message": payload.message,
        "note": "Connect to your preferred LLM provider with this context to generate responses.",
    }

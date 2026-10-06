"""
SecurityOS Attestations API

Manages third-party coverage attestations — explicit, authenticated
confirmations that a named security platform covers a set of controls.

Routes:
  POST   /api/v1/securityos/organizations/{org_id}/attestations
  GET    /api/v1/securityos/organizations/{org_id}/attestations
  GET    /api/v1/securityos/organizations/{org_id}/attestations/{attest_id}
  POST   /api/v1/securityos/organizations/{org_id}/attestations/{attest_id}/revoke
  GET    /api/v1/securityos/organizations/{org_id}/attestations/expiring
  GET    /api/v1/securityos/organizations/{org_id}/attestations/recommendations
  GET    /api/v1/securityos/providers
  GET    /api/v1/securityos/providers/{provider_id}

Authentication: every org-scoped route requires a valid Bearer JWT.
Actor identity (created_by_*, revoked_by_*) is always sourced from the JWT —
never from the request body.
"""

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from backend.auth.context import Principal, get_principal, require_org_access
from backend.auth.permissions import (
    PERM_ATTESTATION_CREATE,
    PERM_ATTESTATION_REVOKE,
    PERM_FINDING_VIEW,
    require_permission,
)
from backend.repositories.control_state_repo import attestation_repo
from backend.repositories.audit_repo import audit_repo
from backend.repositories.finding_repo import finding_repo
from backend.evidence.attestation import (
    AttestationType, AttestationScope,
    CONFIRMATION_PHRASE, ALLOWED_VALIDITY_DAYS, DEFAULT_VALIDITY_DAYS,
    create_attestation, is_active, is_expiring_soon,
    days_until_expiry, refresh_status, to_dict,
)
from backend.evidence.third_party_coverage import (
    PROVIDERS, PROVIDERS_BY_ID, PROVIDERS_BY_CATEGORY,
    recommend_attestation_groups, serialize_provider,
)

router = APIRouter(prefix="/api/v1/securityos", tags=["Attestations"])

# Attestations are append-only (attestation_repo); revocation is a separate
# record and status is derived on read.  backend/controls/state.py reads the
# same repository for scoring.


def _check_not_self_attesting(org_id: str, control_ids: List[str], user_id: str) -> None:
    """
    Separation of duties: whoever did remediation work (start/submit) on a
    finding linked to any of these controls cannot attest them.
    """
    for control_id in control_ids:
        for finding in finding_repo.list_by_control(org_id, control_id):
            if user_id in finding_repo.remediators(finding):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Self-attestation prohibited: you did remediation work on finding "
                        f"'{finding.finding_id}' for control {control_id}. "
                        "A different executive must attest."
                    ),
                )


# ── Pydantic models ───────────────────────────────────────────────────────────

class AttestationCreate(BaseModel):
    """
    Request body for creating an attestation.

    Actor fields (who is attesting) are NOT accepted here — they are set
    server-side from the verified JWT to prevent spoofing.
    Extra fields are forbidden (422) so that old clients sending
    attested_by_name / attested_by_email / user_id receive a clear error.
    """
    model_config = ConfigDict(extra="forbid")

    # What is being attested
    source_provider_id: Optional[str] = None   # ID from the provider catalog
    source_name: str = Field(..., min_length=1, max_length=200)
    source_description: str = Field(..., min_length=1, max_length=2000)
    control_ids: List[str] = Field(..., min_length=1)

    # Confirmation — user must send "ATTEST" exactly
    confirmation_phrase: str = Field(..., description='Must be exactly "ATTEST"')

    # Scope and type
    attestation_type: str = AttestationType.THIRD_PARTY_PLATFORM
    scope_type: str = AttestationScope.EVIDENCE_SOURCE
    validity_days: int = DEFAULT_VALIDITY_DAYS


class RevokeRequest(BaseModel):
    """
    Request body for revoking an attestation.

    Actor fields (revoked_by_*) are set server-side from the JWT.
    """
    model_config = ConfigDict(extra="forbid")

    reason: Optional[str] = None


# ── Provider endpoints (public — no auth required) ────────────────────────────

@router.get("/providers", summary="List all third-party security providers")
def list_providers(category: Optional[str] = None):
    """
    Return the full third-party provider catalog.
    Optionally filter by category: edr, iam, backup, email, siem, firewall, training, mdr, mdm, vuln
    """
    providers = PROVIDERS
    if category:
        providers = [p for p in providers if p.category == category]
    return {
        "providers": [serialize_provider(p) for p in providers],
        "total": len(providers),
        "categories": sorted(set(p.category for p in PROVIDERS)),
    }


@router.get("/providers/{provider_id}", summary="Get one provider and its coverage")
def get_provider(provider_id: str):
    """Return full details for one third-party provider."""
    provider = PROVIDERS_BY_ID.get(provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' not found")
    return serialize_provider(provider)


# ── Attestation CRUD ──────────────────────────────────────────────────────────

@router.post(
    "/organizations/{org_id}/attestations",
    status_code=201,
    summary="Create a new attestation",
)
def create_org_attestation(
    org_id: str,
    payload: AttestationCreate,
    request: Request,
    principal: Principal = Depends(get_principal),
):
    """
    Create a new third-party coverage attestation.

    The caller MUST send confirmation_phrase = "ATTEST" exactly (case-sensitive).
    Actor identity is taken from the JWT — not the request body.
    The server sets all timestamps.
    """
    require_org_access(principal, org_id)
    require_permission(principal, org_id, PERM_ATTESTATION_CREATE)
    _check_not_self_attesting(org_id, payload.control_ids, principal.user_id)

    # Enforce the confirmation phrase — server-side check
    if payload.confirmation_phrase.strip() != CONFIRMATION_PHRASE:
        raise HTTPException(
            status_code=422,
            detail=f'Invalid confirmation phrase. You must type "{CONFIRMATION_PHRASE}" exactly.',
        )

    if payload.validity_days not in ALLOWED_VALIDITY_DAYS:
        raise HTTPException(
            status_code=422,
            detail=f"validity_days must be one of {ALLOWED_VALIDITY_DAYS}.",
        )

    # Validate provider ID if supplied
    if payload.source_provider_id:
        if not PROVIDERS_BY_ID.get(payload.source_provider_id):
            raise HTTPException(
                status_code=404,
                detail=f"Provider '{payload.source_provider_id}' not found in the coverage catalog.",
            )

    try:
        attest = create_attestation(
            organization_id=org_id,
            # Actor always comes from the verified JWT
            created_by_user_id=principal.user_id,
            created_by_name=principal.display_name,
            created_by_email=principal.email,
            attestation_type=payload.attestation_type,
            scope_type=payload.scope_type,
            control_ids=payload.control_ids,
            source_provider_id=payload.source_provider_id,
            source_name=payload.source_name,
            source_description=payload.source_description,
            validity_days=payload.validity_days,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    attestation_repo.add(attest)
    audit_repo.record(org_id=org_id, actor_user_id=principal.user_id, action="attestation.created",
                      attestation_id=attest.id, control_ids=list(attest.control_ids),
                      source_name=attest.source_name)

    return {
        "attestation": to_dict(attest),
        "control_ids_attested": attest.control_ids,
        "message": (
            f"Attestation created. {len(attest.control_ids)} control(s) now show "
            f"Attested Third-Party coverage. Expires in {attest.validity_days} days."
        ),
    }


@router.get(
    "/organizations/{org_id}/attestations",
    summary="List all attestations for an org",
)
def list_org_attestations(
    org_id: str,
    status: Optional[str] = None,        # "active" | "expired" | "revoked"
    include_expired: bool = False,
    principal: Principal = Depends(get_principal),
):
    """
    Return all attestations for an organization.
    Refreshes expiry status before returning.
    """
    require_org_access(principal, org_id)
    require_permission(principal, org_id, PERM_FINDING_VIEW)

    results = []
    for attest in attestation_repo.list_by_org(org_id):
        refresh_status(attest)
        if status and attest.status != status:
            continue
        if not include_expired and attest.status == "expired":
            continue
        results.append(to_dict(attest))

    # Sort: active first, then by expiry date ascending
    results.sort(key=lambda a: (
        0 if a["status"] == "active" else 1 if a["status"] == "expired" else 2,
        a["expires_at"] or "",
    ))

    active_count  = sum(1 for a in results if a["status"] == "active")
    expired_count = sum(1 for a in results if a["status"] == "expired")
    revoked_count = sum(1 for a in results if a["status"] == "revoked")

    return {
        "org_id": org_id,
        "attestations": results,
        "total": len(results),
        "active": active_count,
        "expired": expired_count,
        "revoked": revoked_count,
    }


@router.get(
    "/organizations/{org_id}/attestations/expiring",
    summary="List attestations expiring soon",
)
def list_expiring_attestations(
    org_id: str,
    principal: Principal = Depends(get_principal),
):
    """Return active attestations that expire within the warning window (default 14 days)."""
    require_org_access(principal, org_id)
    require_permission(principal, org_id, PERM_FINDING_VIEW)

    expiring = []
    for attest in attestation_repo.list_by_org(org_id):
        refresh_status(attest)
        if is_active(attest) and is_expiring_soon(attest):
            expiring.append({
                **to_dict(attest),
                "days_remaining": days_until_expiry(attest),
            })
    expiring.sort(key=lambda a: a["days_remaining"])
    return {"org_id": org_id, "expiring": expiring, "total": len(expiring)}


@router.get(
    "/organizations/{org_id}/attestations/recommendations",
    summary="Suggest grouped attestations for failing controls",
)
def get_attestation_recommendations(
    org_id: str,
    control_ids: str = "",
    principal: Principal = Depends(get_principal),
):
    """
    Given a comma-separated list of failing/unknown control IDs, suggest
    which third-party providers could cover them via grouped attestation.
    """
    require_org_access(principal, org_id)
    require_permission(principal, org_id, PERM_FINDING_VIEW)

    ids = [c.strip() for c in control_ids.split(",") if c.strip()] if control_ids else []
    if not ids:
        return {"recommendations": [], "message": "Provide control_ids as a comma-separated query parameter."}

    groups = recommend_attestation_groups(ids)

    return {
        "failing_control_ids": ids,
        "recommendations": [
            {
                "provider": serialize_provider(g["provider"]),
                "covered_controls": g["covered_controls"],
                "coverage_count": g["coverage_count"],
                "message": (
                    f"{g['provider'].name} could cover {g['coverage_count']} of your "
                    f"failing control(s) with one attestation."
                ),
            }
            for g in groups
        ],
        "total": len(groups),
    }


@router.get(
    "/organizations/{org_id}/attestations/{attest_id}",
    summary="Get one attestation",
)
def get_org_attestation(
    org_id: str,
    attest_id: str,
    principal: Principal = Depends(get_principal),
):
    """Return a single attestation record with current status."""
    require_org_access(principal, org_id)
    require_permission(principal, org_id, PERM_FINDING_VIEW)

    attest = attestation_repo.get(org_id, attest_id)
    if not attest:
        raise HTTPException(status_code=404, detail=f"Attestation '{attest_id}' not found")
    refresh_status(attest)
    return to_dict(attest)


@router.post(
    "/organizations/{org_id}/attestations/{attest_id}/revoke",
    summary="Revoke an attestation",
)
def revoke_org_attestation(
    org_id: str,
    attest_id: str,
    payload: RevokeRequest,
    principal: Principal = Depends(get_principal),
):
    """
    Revoke an attestation. Sets status=REVOKED with revoked_at timestamp.
    Does not delete the record — preserves full audit history.
    Actor (revoked_by_*) is always taken from the JWT.
    """
    require_org_access(principal, org_id)
    require_permission(principal, org_id, PERM_ATTESTATION_REVOKE)

    try:
        attest = attestation_repo.revoke(
            org_id, attest_id,
            revoked_by_user_id=principal.user_id,
            revoked_by_name=principal.display_name,
            reason=payload.reason,
        )
    except LookupError:
        raise HTTPException(status_code=404, detail=f"Attestation '{attest_id}' not found")
    except ValueError:
        raise HTTPException(status_code=409, detail="Attestation is already revoked.")
    audit_repo.record(org_id=org_id, actor_user_id=principal.user_id, action="attestation.revoked",
                      attestation_id=attest_id, reason=payload.reason)

    return {
        "attestation_id": attest_id,
        "status": "revoked",
        "revoked_at": attest.revoked_at,
        "revoked_by_name": attest.revoked_by_name,
        "affected_controls": attest.control_ids,
        "message": (
            f"Attestation revoked. {len(attest.control_ids)} control(s) will revert "
            f"to unverified status. Re-attest or connect an integration to restore coverage."
        ),
    }


@router.get(
    "/organizations/{org_id}/attestations/{attest_id}/reconfirm",
    summary="Get reconfirmation prompt for an expiring attestation",
)
def get_reconfirm_prompt(
    org_id: str,
    attest_id: str,
    principal: Principal = Depends(get_principal),
):
    """
    Return the context needed to reconfirm an expiring attestation.
    The client should show the original attestation context and prompt
    for a fresh ATTEST confirmation.
    """
    require_org_access(principal, org_id)
    require_permission(principal, org_id, PERM_FINDING_VIEW)

    attest = attestation_repo.get(org_id, attest_id)
    if not attest:
        raise HTTPException(status_code=404, detail=f"Attestation '{attest_id}' not found")
    refresh_status(attest)
    return {
        "attestation": to_dict(attest),
        "reconfirm_required": attest.status in ("expired",) or is_expiring_soon(attest),
        "confirmation_phrase": CONFIRMATION_PHRASE,
        "validity_options": ALLOWED_VALIDITY_DAYS,
        "default_validity_days": DEFAULT_VALIDITY_DAYS,
    }

"""
SecurityOS Organizations & Invites API — Phase 2.1

How anyone gets into the product:

  POST   /api/v1/securityos/organizations
         Self-serve: create an org.  Server generates the org_id.  The caller
         becomes its admin (and, optionally, its executive — the small-business
         case where the owner is both; this is recorded in the audit log).

  POST   /api/v1/securityos/organizations/{org_id}/invites        (org.manage)
  GET    /api/v1/securityos/organizations/{org_id}/invites        (org.manage)
  DELETE /api/v1/securityos/organizations/{org_id}/invites/{id}   (org.manage)
         Single-use, expiring, role-bound invite links.

  POST   /api/v1/securityos/invites/accept
         The invitee accepts with the raw token.  Their identity comes from
         their JWT.  This is how a client's CEO joins an MSP-provisioned org.

  GET    /api/v1/securityos/organizations/{org_id}/audit          (audit.export)
  GET    /api/v1/securityos/organizations/{org_id}/audit/verify   (audit.export)
         The org's hash-chained audit trail, and a tamper check over it.

Separation-of-duties rules enforced here:
  - The executive role can only be obtained via invite (or by the creator of a
    self-serve org).  It can never be added directly by user_id or via PATCH.
  - MSP staff cannot accept an executive invite into an org managed by their
    own MSP: the client signs off, never the MSP.
  - Auditor invites must carry a membership expiry.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from backend.auth.context import Principal, get_principal, require_org_access
from backend.auth.permissions import (
    PERM_AUDIT_EXPORT,
    PERM_ORG_MANAGE,
    effective_permissions,
    require_permission,
)
from backend.repositories.audit_repo import audit_repo
from backend.repositories.invite_repo import (
    DEFAULT_INVITE_DAYS,
    MAX_INVITE_DAYS,
    Invite,
    invite_repo,
)
from backend.repositories.org_membership_repo import (
    ROLES_REQUIRING_EXPIRY,
    VALID_ROLES,
    OrgMembership,
    org_membership_repo,
    parse_iso,
    utcnow,
)
from backend.repositories.org_repo import org_repo
from backend.repositories.user_repo import user_repo

router = APIRouter(prefix="/api/v1/securityos", tags=["Organizations"])


# ── Models ────────────────────────────────────────────────────────────────────

class OrganizationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=200)
    industry: str = ""
    employee_count: str = ""
    email_provider: str = ""
    cloud_providers: List[str] = []
    sensitive_data: List[str] = []
    also_executive: bool = Field(
        False,
        description=(
            "Also grant the creator the executive role (owner-operated small "
            "business).  Recorded in the audit log as a combined admin+executive holder."
        ),
    )


class InviteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str = Field(..., description=f"One of: {sorted(VALID_ROLES)}")
    valid_days: int = Field(DEFAULT_INVITE_DAYS, ge=1, le=MAX_INVITE_DAYS)
    email_hint: Optional[str] = Field(None, max_length=320)
    membership_expires_at: Optional[str] = Field(
        None, description="ISO-8601. Required for auditor invites."
    )


class InviteAccept(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(..., min_length=20, max_length=200)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_future_iso(value: Optional[str], field_name: str) -> Optional[str]:
    """Parse and require a future ISO-8601 timestamp; return it normalised to UTC."""
    if value is None:
        return None
    try:
        dt = parse_iso(value)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"'{field_name}' must be an ISO-8601 datetime.")
    if dt <= utcnow():
        raise HTTPException(status_code=422, detail=f"'{field_name}' must be in the future.")
    return dt.isoformat()


def _serialize_invite(inv: Invite) -> dict:
    return {
        "invite_id": inv.invite_id,
        "org_id": inv.org_id,
        "role": inv.role,
        "status": inv.status,
        "created_by": inv.created_by,
        "created_at": inv.created_at,
        "expires_at": inv.expires_at,
        "email_hint": inv.email_hint,
        "membership_expires_at": inv.membership_expires_at,
        "accepted_by": inv.accepted_by,
        "accepted_at": inv.accepted_at,
    }


def grant_role(
    *,
    user_id: str,
    org_id: str,
    role: str,
    granted_by: str,
    expires_at: Optional[str] = None,
    via: str,
) -> OrgMembership:
    """Create a membership row and audit it.  Flags combined admin+executive holders."""
    membership = OrgMembership(
        user_id=user_id,
        org_id=org_id,
        role=role,
        granted_by=granted_by,
        granted_at=_now_iso(),
        expires_at=expires_at,
    )
    try:
        org_membership_repo.add(membership)
    except KeyError as exc:
        raise HTTPException(status_code=409, detail=str(exc).strip("'\""))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    roles_now = org_membership_repo.active_roles(user_id, org_id)
    audit_repo.record(
        org_id=org_id,
        actor_user_id=granted_by,
        action="membership.granted",
        target_user_id=user_id,
        role=role,
        via=via,
        expires_at=expires_at,
        self_grant=(granted_by == user_id),
        holds_admin_and_executive={"admin", "executive"} <= roles_now,
    )
    return membership


# ── Self-serve org creation ───────────────────────────────────────────────────

@router.post("/organizations", status_code=201, summary="Create an organization (self-serve)")
def create_organization(
    payload: OrganizationCreate,
    principal: Principal = Depends(get_principal),
):
    user_repo.upsert(principal.user_id, principal.email, principal.display_name)
    org = org_repo.create(
        name=payload.name,
        created_by=principal.user_id,
        profile={
            "industry": payload.industry,
            "employee_count": payload.employee_count,
            "email_provider": payload.email_provider,
            "cloud_providers": payload.cloud_providers,
            "sensitive_data": payload.sensitive_data,
        },
    )
    audit_repo.record(
        org_id=org.org_id, actor_user_id=principal.user_id, action="org.created", via="self_serve"
    )
    grant_role(user_id=principal.user_id, org_id=org.org_id, role="admin",
               granted_by=principal.user_id, via="org_bootstrap")
    if payload.also_executive:
        grant_role(user_id=principal.user_id, org_id=org.org_id, role="executive",
                   granted_by=principal.user_id, via="org_bootstrap")

    roles = sorted(org_membership_repo.active_roles(principal.user_id, org.org_id))
    return {
        "org_id": org.org_id,
        "name": org.name,
        "created_at": org.created_at,
        "your_roles": roles,
    }


# ── Invites ───────────────────────────────────────────────────────────────────

@router.post("/organizations/{org_id}/invites", status_code=201, summary="Create an invite link")
def create_invite(
    org_id: str,
    payload: InviteCreate,
    principal: Principal = Depends(get_principal),
):
    require_org_access(principal, org_id)
    require_permission(principal, org_id, PERM_ORG_MANAGE)

    if payload.role not in VALID_ROLES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid role '{payload.role}'. Must be one of {sorted(VALID_ROLES)}.",
        )
    membership_expires_at = validate_future_iso(payload.membership_expires_at, "membership_expires_at")
    if payload.role in ROLES_REQUIRING_EXPIRY and not membership_expires_at:
        raise HTTPException(
            status_code=422,
            detail=f"Invites for role '{payload.role}' require membership_expires_at.",
        )

    invite, raw_token = invite_repo.create(
        org_id=org_id,
        role=payload.role,
        created_by=principal.user_id,
        valid_days=payload.valid_days,
        email_hint=payload.email_hint,
        membership_expires_at=membership_expires_at,
    )
    audit_repo.record(
        org_id=org_id, actor_user_id=principal.user_id, action="invite.created",
        invite_id=invite.invite_id, role=invite.role, expires_at=invite.expires_at,
    )
    return {
        "invite": _serialize_invite(invite),
        # Returned exactly once.  Only a hash is stored.
        "token": raw_token,
        "message": "Share this token with the invitee. It is shown only once.",
    }


@router.get("/organizations/{org_id}/invites", summary="List invites (tokens are never returned)")
def list_invites(org_id: str, principal: Principal = Depends(get_principal)):
    require_org_access(principal, org_id)
    require_permission(principal, org_id, PERM_ORG_MANAGE)
    invites = invite_repo.list_by_org(org_id)
    return {"org_id": org_id, "invites": [_serialize_invite(i) for i in invites], "total": len(invites)}


@router.delete("/organizations/{org_id}/invites/{invite_id}", status_code=204, summary="Revoke an invite")
def revoke_invite(org_id: str, invite_id: str, principal: Principal = Depends(get_principal)):
    require_org_access(principal, org_id)
    require_permission(principal, org_id, PERM_ORG_MANAGE)
    invite = invite_repo.revoke(invite_id, org_id)
    if invite is None:
        raise HTTPException(status_code=404, detail=f"Invite '{invite_id}' not found.")
    audit_repo.record(org_id=org_id, actor_user_id=principal.user_id, action="invite.revoked",
                      invite_id=invite_id)


@router.post("/invites/accept", summary="Accept an invite")
def accept_invite(payload: InviteAccept, principal: Principal = Depends(get_principal)):
    user_repo.upsert(principal.user_id, principal.email, principal.display_name)
    invite = invite_repo.find_by_token(payload.token)
    # Same response for unknown, revoked, used, and expired tokens: no oracle.
    if invite is None or invite.status != "pending":
        raise HTTPException(status_code=404, detail="Invite not found or no longer valid.")

    org = org_repo.get(invite.org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Invite not found or no longer valid.")

    if invite.role == "executive" and principal.msp_id and principal.msp_id == org.msp_id:
        audit_repo.record(
            org_id=org.org_id, actor_user_id=principal.user_id, action="invite.rejected",
            invite_id=invite.invite_id, reason="msp_staff_cannot_be_client_executive",
        )
        raise HTTPException(
            status_code=403,
            detail=(
                "Staff of the managing MSP cannot hold the executive role in a client org. "
                "The client's own leadership must accept this invite."
            ),
        )

    membership = grant_role(
        user_id=principal.user_id,
        org_id=invite.org_id,
        role=invite.role,
        granted_by=invite.created_by,
        expires_at=invite.membership_expires_at,
        via=f"invite:{invite.invite_id}",
    )
    try:
        invite_repo.mark_accepted(invite, principal.user_id)
    except ValueError:
        # Lost a race with a concurrent accept: undo this grant.
        org_membership_repo.remove_role(principal.user_id, invite.org_id, invite.role)
        raise HTTPException(status_code=404, detail="Invite not found or no longer valid.")

    return {
        "org_id": invite.org_id,
        "role": membership.role,
        "expires_at": membership.expires_at,
        "your_roles": sorted(org_membership_repo.active_roles(principal.user_id, invite.org_id)),
        "your_permissions": sorted(effective_permissions(principal, invite.org_id)),
    }


# ── Audit trail ───────────────────────────────────────────────────────────────

@router.get("/organizations/{org_id}/audit", summary="Audit trail for this org")
def get_audit_trail(org_id: str, principal: Principal = Depends(get_principal)):
    require_org_access(principal, org_id)
    require_permission(principal, org_id, PERM_AUDIT_EXPORT)
    events = audit_repo.list_by_org(org_id)
    return {"org_id": org_id, "events": events, "total": len(events)}


@router.get("/organizations/{org_id}/audit/verify", summary="Verify the audit log hash chain")
def verify_audit_trail(org_id: str, principal: Principal = Depends(get_principal)):
    """
    Recompute every hash in this org's audit chain.  `valid: false` means a row
    was edited or removed after it was written; `first_break_seq` points at it.
    """
    require_org_access(principal, org_id)
    require_permission(principal, org_id, PERM_AUDIT_EXPORT)
    return {"org_id": org_id, **audit_repo.verify(org_id)}

"""
SecurityOS Members API — Phase 2.1

Routes:
  GET    /api/v1/securityos/me
  GET    /api/v1/securityos/organizations/{org_id}/members
  POST   /api/v1/securityos/organizations/{org_id}/members
  PATCH  /api/v1/securityos/organizations/{org_id}/members/{user_id}
  DELETE /api/v1/securityos/organizations/{org_id}/members/{user_id}[?role=...]

Authorization:
  - GET /me — any authenticated caller
  - All org-member routes — org.manage

Phase 2.1 rules:
  - Roles are additive (a user may hold several).
  - The executive role can NOT be granted here, by direct add or PATCH.  It comes
    only from an invite (POST /organizations/{id}/invites) or org bootstrap, so
    the system knows who accepted it and can block MSP staff from holding it.
  - Auditor grants require expires_at.
  - The last admin cannot be removed or lose the admin role.
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from backend.api.orgs import grant_role, validate_future_iso
from backend.auth.context import Principal, get_principal, require_org_access
from backend.auth.permissions import (
    PERM_FINDING_ASSIGN,
    PERM_FINDING_REMEDIATE,
    PERM_ORG_MANAGE,
    permissions_for_roles,
    require_permission,
)
from backend.repositories.audit_repo import audit_repo
from backend.repositories.org_membership_repo import (
    ROLES_REQUIRING_EXPIRY,
    VALID_ROLES,
    OrgMembership,
    org_membership_repo,
)
from backend.repositories.org_repo import org_repo
from backend.repositories.user_repo import describe, user_repo

router = APIRouter(prefix="/api/v1/securityos", tags=["Members"])

INVITE_ONLY_ROLES = frozenset({"executive"})


# ── Pydantic models ───────────────────────────────────────────────────────────

class MemberAdd(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(..., min_length=1, description="The user_id from their JWT sub claim")
    role: str = Field(..., description=f"One of: {sorted(VALID_ROLES - INVITE_ONLY_ROLES)}")
    expires_at: Optional[str] = Field(None, description="ISO-8601 expiry (required for auditor)")


class MemberRolesUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    roles: List[str] = Field(..., min_length=1, description="The complete set of roles to keep")


def _serialize_membership(m: OrgMembership) -> dict:
    return {
        "user_id": m.user_id,
        "org_id": m.org_id,
        "role": m.role,
        "granted_by": m.granted_by,
        "granted_at": m.granted_at,
        "expires_at": m.expires_at,
    }


def _validate_roles(roles) -> None:
    bad = sorted(set(roles) - VALID_ROLES)
    if bad:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid role(s) {bad}. Must be one of {sorted(VALID_ROLES)}.",
        )


def _ensure_not_last_admin(org_id: str, user_id: str, keeps_admin: bool) -> None:
    if keeps_admin:
        return
    admins = org_membership_repo.users_with_role(org_id, "admin")
    if admins == [user_id]:
        raise HTTPException(
            status_code=409,
            detail="This user is the last admin in the org. Add another admin first.",
        )


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/me", summary="Your identity, memberships, and effective permissions")
def get_me(principal: Principal = Depends(get_principal)):
    """Identity from the JWT; roles and permissions from active memberships."""
    user_repo.upsert(principal.user_id, principal.email, principal.display_name)
    by_org: dict = {}
    for m in org_membership_repo.list_by_user(principal.user_id):
        by_org.setdefault(m.org_id, []).append(m)

    orgs = []
    for org_id, rows in sorted(by_org.items()):
        roles = sorted({m.role for m in rows})
        org = org_repo.get(org_id)
        if org is None:
            continue  # deleted org
        orgs.append({
            "org_id": org_id,
            "org_name": org.name,
            "msp_id": org.msp_id,
            "roles": roles,
            "permissions": sorted(permissions_for_roles(roles)),
            "memberships": [_serialize_membership(m) for m in rows],
        })

    return {
        "user_id": principal.user_id,
        "email": principal.email,
        "display_name": principal.display_name,
        "msp_id": principal.msp_id,
        "organizations": orgs,
    }


@router.get("/organizations/{org_id}/members", summary="List active members of an org")
def list_org_members(
    org_id: str,
    include_expired: bool = False,
    principal: Principal = Depends(get_principal),
):
    require_org_access(principal, org_id)
    require_permission(principal, org_id, PERM_ORG_MANAGE)

    members = org_membership_repo.list_by_org(org_id, include_expired=include_expired)
    people = {p["user_id"]: p for p in describe(m.user_id for m in members)}
    return {
        "org_id": org_id,
        "members": [{**_serialize_membership(m), "user": people[m.user_id]} for m in members],
        "total": len(members),
    }


@router.get("/organizations/{org_id}/assignees", summary="People who can be assigned remediation work")
def list_assignees(org_id: str, principal: Principal = Depends(get_principal)):
    """Active members who can remediate.  Requires finding.assign (no org.manage needed)."""
    require_org_access(principal, org_id)
    require_permission(principal, org_id, PERM_FINDING_ASSIGN)
    by_user: dict = {}
    for m in org_membership_repo.list_by_org(org_id):
        by_user.setdefault(m.user_id, set()).add(m.role)
    eligible = [u for u, roles in by_user.items() if PERM_FINDING_REMEDIATE in permissions_for_roles(roles)]
    people = describe(sorted(eligible))
    for p in people:
        p["roles"] = sorted(by_user[p["user_id"]])
    return {"org_id": org_id, "assignees": people}


@router.post("/organizations/{org_id}/members", status_code=201, summary="Grant a role to a user")
def add_member(
    org_id: str,
    payload: MemberAdd,
    principal: Principal = Depends(get_principal),
):
    require_org_access(principal, org_id)
    require_permission(principal, org_id, PERM_ORG_MANAGE)

    _validate_roles([payload.role])
    if payload.role in INVITE_ONLY_ROLES:
        raise HTTPException(
            status_code=422,
            detail="The executive role can only be granted through an invite "
                   "(POST /organizations/{org_id}/invites).",
        )
    expires_at = validate_future_iso(payload.expires_at, "expires_at")
    if payload.role in ROLES_REQUIRING_EXPIRY and not expires_at:
        raise HTTPException(status_code=422, detail=f"Role '{payload.role}' requires expires_at.")

    membership = grant_role(
        user_id=payload.user_id, org_id=org_id, role=payload.role,
        granted_by=principal.user_id, expires_at=expires_at, via="direct_add",
    )
    return {
        "message": f"User '{payload.user_id}' granted '{payload.role}' in org '{org_id}'.",
        "membership": _serialize_membership(membership),
    }


@router.patch("/organizations/{org_id}/members/{target_user_id}", summary="Set a member's roles")
def set_member_roles(
    org_id: str,
    target_user_id: str,
    payload: MemberRolesUpdate,
    principal: Principal = Depends(get_principal),
):
    """
    Replace the member's role set with `roles`.  Roles may be removed freely
    (subject to the last-admin rule) but executive cannot be ADDED here.
    """
    require_org_access(principal, org_id)
    require_permission(principal, org_id, PERM_ORG_MANAGE)

    wanted = set(payload.roles)
    _validate_roles(wanted)

    current = org_membership_repo.active_roles(target_user_id, org_id)
    if not current:
        raise HTTPException(status_code=404, detail=f"User '{target_user_id}' is not a member of org '{org_id}'.")

    to_add = wanted - current
    to_remove = current - wanted

    if to_add & INVITE_ONLY_ROLES:
        raise HTTPException(
            status_code=422,
            detail="The executive role can only be granted through an invite.",
        )
    if to_add & ROLES_REQUIRING_EXPIRY:
        raise HTTPException(
            status_code=422,
            detail="Auditor access must be granted with an expiry via POST /members or an invite.",
        )
    _ensure_not_last_admin(org_id, target_user_id, keeps_admin="admin" in wanted or "admin" not in current)

    for role in sorted(to_remove):
        org_membership_repo.remove_role(target_user_id, org_id, role)
        audit_repo.record(org_id=org_id, actor_user_id=principal.user_id, action="membership.revoked",
                          target_user_id=target_user_id, role=role)
    for role in sorted(to_add):
        grant_role(user_id=target_user_id, org_id=org_id, role=role,
                   granted_by=principal.user_id, via="role_update")

    rows = org_membership_repo.list_by_org(org_id)
    return {
        "user_id": target_user_id,
        "roles": sorted(org_membership_repo.active_roles(target_user_id, org_id)),
        "memberships": [_serialize_membership(m) for m in rows if m.user_id == target_user_id],
    }


@router.delete(
    "/organizations/{org_id}/members/{target_user_id}",
    status_code=204,
    summary="Remove a member (or one role with ?role=)",
)
def remove_member(
    org_id: str,
    target_user_id: str,
    role: Optional[str] = None,
    principal: Principal = Depends(get_principal),
):
    require_org_access(principal, org_id)
    require_permission(principal, org_id, PERM_ORG_MANAGE)

    current = org_membership_repo.active_roles(target_user_id, org_id)
    if not current or (role is not None and role not in current):
        raise HTTPException(status_code=404, detail=f"User '{target_user_id}' does not hold that membership.")

    removing = {role} if role else current
    _ensure_not_last_admin(org_id, target_user_id, keeps_admin="admin" not in removing)

    for r in sorted(removing):
        org_membership_repo.remove_role(target_user_id, org_id, r)
        audit_repo.record(org_id=org_id, actor_user_id=principal.user_id, action="membership.revoked",
                          target_user_id=target_user_id, role=r)

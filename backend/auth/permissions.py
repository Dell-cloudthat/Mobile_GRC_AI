"""
SecurityOS Permission System — Phase 2.1

Security invariants:
  - Identity comes only from a verified JWT.
  - Authorization comes only from org_memberships (active, non-expired rows),
    never from token role or org claims.
  - Deny by default: no active membership → 404 (tenant isolation, in
    require_org_access); membership without the permission → 403.
  - Permission checks, not role-name checks.
  - Roles are additive: a user's permissions are the union of their active roles.
  - Separation of duties: admins manage the org but cannot attest, approve,
    remediate, or accept risk.  Whoever did remediation work cannot approve a
    High/Critical fix or attest the same controls (enforced in the routers).

Role matrix (the single source of truth — tests assert against this table):

| Permission                | admin | executive | engineer | msp_technician | auditor |
|---------------------------|:-----:|:---------:|:--------:|:--------------:|:-------:|
| finding.view              |   ✓   |     ✓     |    ✓     |       ✓        |    ✓    |
| finding.assign            |   ✓   |     ✓     |          |       ✓        |         |
| finding.remediate         |       |           |    ✓     |       ✓        |         |
| finding.approve_close     |       |     ✓     |          |                |         |
| attestation.create        |       |     ✓     |          |                |         |
| attestation.revoke        |       |     ✓     |          |                |         |
| risk.accept               |       |     ✓     |          |                |         |
| org.manage                |   ✓   |           |          |                |         |
| billing.manage            |   ✓   |           |          |                |         |
| audit.export              |   ✓   |     ✓     |          |                |    ✓    |
| ai.import                 |   ✓   |           |    ✓     |       ✓        |         |
| ai.decide                 |       |     ✓     |          |                |         |

Shadow AI (v1): anyone with finding.view sees the AI inventory.  Importing
discovery data is operational work (admin, engineer, MSP technician).
Approving, blocking or accepting the risk of an AI tool is a business policy
decision, so only an executive of the client makes it.
"""

from __future__ import annotations

from typing import Dict, FrozenSet, Iterable, Set

from fastapi import HTTPException

from backend.auth.context import Principal
from backend.repositories.org_membership_repo import org_membership_repo

# ── Permission constants ───────────────────────────────────────────────────────

PERM_FINDING_VIEW          = "finding.view"
PERM_FINDING_ASSIGN        = "finding.assign"
PERM_FINDING_REMEDIATE     = "finding.remediate"
PERM_FINDING_APPROVE_CLOSE = "finding.approve_close"
PERM_ATTESTATION_CREATE    = "attestation.create"
PERM_ATTESTATION_REVOKE    = "attestation.revoke"
PERM_RISK_ACCEPT           = "risk.accept"
PERM_ORG_MANAGE            = "org.manage"
PERM_BILLING_MANAGE        = "billing.manage"
PERM_AUDIT_EXPORT          = "audit.export"
PERM_AI_IMPORT             = "ai.import"
PERM_AI_DECIDE             = "ai.decide"

ALL_PERMISSIONS: FrozenSet[str] = frozenset({
    PERM_FINDING_VIEW, PERM_FINDING_ASSIGN, PERM_FINDING_REMEDIATE,
    PERM_FINDING_APPROVE_CLOSE, PERM_ATTESTATION_CREATE, PERM_ATTESTATION_REVOKE,
    PERM_RISK_ACCEPT, PERM_ORG_MANAGE, PERM_BILLING_MANAGE, PERM_AUDIT_EXPORT,
    PERM_AI_IMPORT, PERM_AI_DECIDE,
})

# Backwards-compatible aliases for names used in Phase 2 code.
PERM_FINDING_RISK_ACCEPT = PERM_RISK_ACCEPT
PERM_REPORT_VIEW = PERM_FINDING_VIEW

# ── Role → permission map ─────────────────────────────────────────────────────

ROLE_PERMISSIONS: Dict[str, FrozenSet[str]] = {
    "admin": frozenset({
        PERM_ORG_MANAGE,
        PERM_BILLING_MANAGE,
        PERM_FINDING_VIEW,
        PERM_FINDING_ASSIGN,
        PERM_AUDIT_EXPORT,
        PERM_AI_IMPORT,
    }),
    "executive": frozenset({
        PERM_FINDING_VIEW,
        PERM_FINDING_ASSIGN,
        PERM_FINDING_APPROVE_CLOSE,
        PERM_ATTESTATION_CREATE,
        PERM_ATTESTATION_REVOKE,
        PERM_RISK_ACCEPT,
        PERM_AUDIT_EXPORT,
        PERM_AI_DECIDE,
    }),
    "engineer": frozenset({
        PERM_FINDING_VIEW,
        PERM_FINDING_REMEDIATE,
        PERM_AI_IMPORT,
    }),
    "msp_technician": frozenset({
        PERM_FINDING_VIEW,
        PERM_FINDING_ASSIGN,
        PERM_FINDING_REMEDIATE,
        PERM_AI_IMPORT,
    }),
    "auditor": frozenset({
        PERM_FINDING_VIEW,
        PERM_AUDIT_EXPORT,
    }),
}


# ── Lookups ────────────────────────────────────────────────────────────────────

def permissions_for_roles(roles: Iterable[str]) -> Set[str]:
    perms: Set[str] = set()
    for role in roles:
        perms |= ROLE_PERMISSIONS.get(role, frozenset())
    return perms


def effective_permissions(principal: Principal, org_id: str) -> Set[str]:
    """Union of permissions across the principal's ACTIVE roles in org_id."""
    return permissions_for_roles(org_membership_repo.active_roles(principal.user_id, org_id))


def has_permission(principal: Principal, org_id: str, permission: str) -> bool:
    return permission in effective_permissions(principal, org_id)


def require_permission(principal: Principal, org_id: str, permission: str) -> None:
    """
    Raise HTTP 403 if the principal lacks `permission` in org_id.
    Call AFTER require_org_access() so non-members get 404 first.
    """
    if not has_permission(principal, org_id, permission):
        raise HTTPException(
            status_code=403,
            detail=f"Permission '{permission}' is required for this action.",
        )


def require_any_permission(principal: Principal, org_id: str, *permissions: str) -> None:
    perms = effective_permissions(principal, org_id)
    if not perms.intersection(permissions):
        raise HTTPException(
            status_code=403,
            detail=f"One of these permissions is required: {sorted(permissions)}.",
        )


def get_roles(principal: Principal, org_id: str) -> Set[str]:
    return org_membership_repo.active_roles(principal.user_id, org_id)

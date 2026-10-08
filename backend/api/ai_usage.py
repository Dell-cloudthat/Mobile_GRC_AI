"""
SecurityOS Shadow AI API — v1.

Routes:
  GET  /api/v1/securityos/organizations/{org_id}/ai-apps                 inventory + summary
  GET  /api/v1/securityos/organizations/{org_id}/ai-apps/{app_key}       one app: risk, intel, users, history
  POST /api/v1/securityos/organizations/{org_id}/ai-apps/import          CSV discovery import
  POST /api/v1/securityos/organizations/{org_id}/ai-apps/{app_key}/decision
  GET  /api/v1/securityos/ai-catalog                                     catalog (any signed-in user)
  GET  /api/v1/securityos/ai-catalog/{app_id}
  GET  /api/v1/securityos/msp/{msp_id}/ai-usage                          portfolio rollup for MSPs

Authorization (see backend/auth/permissions.py):
  read: finding.view · import: ai.import · decide: ai.decide (executive only)
Every import and decision is written to the org's hash-chained audit log.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.ai_governance import catalog, service
from backend.ai_governance.importers import ImportError_, parse_csv
from backend.ai_governance.matcher import is_unlisted
from backend.auth.context import Principal, get_principal, require_msp_access, require_org_access
from backend.auth.permissions import (
    PERM_AI_DECIDE,
    PERM_AI_IMPORT,
    PERM_FINDING_VIEW,
    has_permission,
    require_permission,
)
from backend.repositories.ai_usage_repo import ai_usage_repo, new_decision
from backend.repositories.audit_repo import audit_repo
from backend.repositories.org_repo import org_repo

router = APIRouter(prefix="/api/v1/securityos", tags=["Shadow AI"])

MAX_RISK_ACCEPT_DAYS = 365
MAX_RISK_ACCEPT_DAYS_CRITICAL = 90


def _profile(org_id: str) -> Dict:
    org = org_repo.get(org_id)
    return dict(org.profile) if org else {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Inventory ─────────────────────────────────────────────────────────────────

@router.get("/organizations/{org_id}/ai-apps", summary="AI apps in use, with risk and status")
def list_ai_apps(org_id: str, principal: Principal = Depends(get_principal)):
    require_org_access(principal, org_id)
    require_permission(principal, org_id, PERM_FINDING_VIEW)
    inv = service.build_inventory(ai_usage_repo.list_observations(org_id),
                                  ai_usage_repo.list_decisions(org_id), _profile(org_id))
    inv["can_import"] = has_permission(principal, org_id, PERM_AI_IMPORT)
    inv["can_decide"] = has_permission(principal, org_id, PERM_AI_DECIDE)
    return inv


@router.get("/organizations/{org_id}/ai-apps/{app_key}", summary="One AI app: risk, intelligence, users")
def get_ai_app(org_id: str, app_key: str, principal: Principal = Depends(get_principal)):
    require_org_access(principal, org_id)
    require_permission(principal, org_id, PERM_FINDING_VIEW)
    obs = ai_usage_repo.get_observation(org_id, app_key)
    if obs is None:
        raise HTTPException(status_code=404, detail="That app hasn't been seen in this organization.")
    detail = service.build_detail(obs, ai_usage_repo.list_decisions(org_id), _profile(org_id))
    detail["can_decide"] = has_permission(principal, org_id, PERM_AI_DECIDE)
    return detail


# ── Import ────────────────────────────────────────────────────────────────────

class ImportBody(BaseModel):
    csv_text: str = Field(..., min_length=1, max_length=6_000_000)
    filename: Optional[str] = Field(None, max_length=200)


@router.post("/organizations/{org_id}/ai-apps/import", summary="Import AI app discovery from a CSV export")
def import_ai_apps(org_id: str, body: ImportBody, principal: Principal = Depends(get_principal)):
    require_org_access(principal, org_id)
    require_permission(principal, org_id, PERM_AI_IMPORT)
    try:
        result = parse_csv(body.csv_text, source="csv")
    except ImportError_ as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    ai_usage_repo.merge_observations(org_id, result.observations)
    listed = [o for o in result.observations if o["listed"]]
    unlisted = [o for o in result.observations if not o["listed"]]
    audit_repo.record(
        org_id=org_id, actor_user_id=principal.user_id, action="ai.import",
        filename=body.filename, rows=result.rows, matched_rows=result.matched_rows,
        apps=[o["app_key"] for o in result.observations],
    )
    return {
        "rows": result.rows,
        "matched_rows": result.matched_rows,
        "ignored_rows": result.ignored_rows,
        "apps_found": len(result.observations),
        "catalog_apps": [o["display_name"] for o in listed],
        "possible_ai_apps": [o["display_name"] for o in unlisted],
        "ignored_examples": result.ignored_samples,
        "columns_used": result.columns,
    }


# ── Decisions ─────────────────────────────────────────────────────────────────

class DecisionBody(BaseModel):
    decision: Literal["approved", "approved_business", "under_review", "blocked", "risk_accepted"]
    note: Optional[str] = Field(None, max_length=2000)
    expires_at: Optional[datetime] = None


@router.post("/organizations/{org_id}/ai-apps/{app_key}/decision", status_code=201,
             summary="Approve, move to business plan, block, or accept the risk of an AI app")
def decide_ai_app(org_id: str, app_key: str, body: DecisionBody, principal: Principal = Depends(get_principal)):
    require_org_access(principal, org_id)
    require_permission(principal, org_id, PERM_AI_DECIDE)
    obs = ai_usage_repo.get_observation(org_id, app_key)
    if obs is None:
        raise HTTPException(status_code=404, detail="That app hasn't been seen in this organization.")

    profile = _profile(org_id)
    history = ai_usage_repo.list_decisions(org_id)
    current = service.build_item(obs, profile, service.latest_decisions(history).get(app_key))
    level = current["risk"]["level"]
    note = (body.note or "").strip() or None
    expires_at = None

    if body.decision == "approved_business":
        app = None if is_unlisted(app_key) else catalog.get(app_key)
        if not app or not app["tiers"].get("business"):
            raise HTTPException(status_code=422, detail="This app has no business plan to approve.")

    if body.decision == "approved" and level in ("critical", "high") and (not note or len(note) < 20):
        raise HTTPException(
            status_code=422,
            detail=f"This app is {level} risk. Say why it's acceptable as-is (at least 20 characters), "
                   "or approve the business plan instead.",
        )

    if body.decision == "risk_accepted":
        if not note or len(note) < 20:
            raise HTTPException(status_code=422, detail="Explain why the risk is acceptable (at least 20 characters).")
        if body.expires_at is None:
            raise HTTPException(status_code=422, detail="Risk acceptance needs an end date.")
        exp = body.expires_at if body.expires_at.tzinfo else body.expires_at.replace(tzinfo=timezone.utc)
        max_days = MAX_RISK_ACCEPT_DAYS_CRITICAL if level == "critical" else MAX_RISK_ACCEPT_DAYS
        if exp <= _now():
            raise HTTPException(status_code=422, detail="The end date must be in the future.")
        if exp > _now() + timedelta(days=max_days):
            raise HTTPException(status_code=422,
                                detail=f"{level.capitalize()}-risk apps can be accepted for at most {max_days} days.")
        expires_at = exp.astimezone(timezone.utc).isoformat()

    record = new_decision(
        app_key=app_key, decision=body.decision, note=note, expires_at=expires_at,
        decided_by_user_id=principal.user_id, decided_by_name=principal.display_name,
    )
    ai_usage_repo.add_decision(org_id, record)
    audit_repo.record(
        org_id=org_id, actor_user_id=principal.user_id, action="ai.decision",
        app_key=app_key, decision=body.decision, risk_level=level, note=note, expires_at=expires_at,
    )
    obs_after = ai_usage_repo.get_observation(org_id, app_key)
    return service.build_detail(obs_after, ai_usage_repo.list_decisions(org_id), profile)


# ── Catalog ───────────────────────────────────────────────────────────────────

@router.get("/ai-catalog", summary="AI app catalog")
def list_catalog(principal: Principal = Depends(get_principal)):
    return {
        "reviewed_at": catalog.reviewed_at(),
        "disclaimer": catalog.disclaimer(),
        "apps": [catalog.public_app(a) for a in catalog.apps()],
    }


@router.get("/ai-catalog/{app_id}", summary="One catalog entry")
def get_catalog_app(app_id: str, principal: Principal = Depends(get_principal)):
    app = catalog.get(app_id)
    if not app:
        raise HTTPException(status_code=404, detail="Not in the catalog.")
    return catalog.public_app(app)


# ── MSP portfolio rollup ──────────────────────────────────────────────────────

@router.get("/msp/{msp_id}/ai-usage", summary="Shadow AI across an MSP's client orgs")
def msp_ai_usage(msp_id: str, principal: Principal = Depends(get_principal)):
    """
    Per-client shadow AI summary plus the patterns worth a conversation:
    which apps show up at the most clients, and which service offers they
    point to.  Only clients the caller can view are included.
    """
    require_msp_access(principal, msp_id)
    orgs = [o for o in org_repo.list_by_msp(msp_id) if has_permission(principal, o.org_id, PERM_FINDING_VIEW)]
    entries = [
        (o.org_id, o.name, service.build_inventory(ai_usage_repo.list_observations(o.org_id),
                                                   ai_usage_repo.list_decisions(o.org_id), dict(o.profile)))
        for o in orgs
    ]
    return {"msp_id": msp_id, **service.portfolio_rollup(entries)}

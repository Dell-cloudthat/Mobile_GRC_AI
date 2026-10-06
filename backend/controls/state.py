"""
Effective control state — Phase 2.1

The ONLY function that decides what status a control has for scoring, the
Trust Passport, and MSP dashboards.  Nobody can set a control to "pass" by
writing a status directly.

Precedence (highest first) for each control:

  1. Open work on a finding linked to the control
     (open / assigned / in_progress / submitted_for_review / reopened,
      or a risk acceptance that has EXPIRED)            → fail / in_progress
  2. Active risk acceptance on a linked finding         → fail, flagged risk_accepted
     (accepted risk is tracked, never scored as passing)
  3. Approved (closed) finding linked to the control    → pass  (evidence: manual,
                                                            reviewed + approved)
  4. Active attestation covering the control            → pass  (evidence:
                                                            attested_third_party)
  5. Manual status (fail / unknown / in_progress only)  → as written
  6. Nothing                                            → unknown

Manual writes of "pass" or "not_applicable" are rejected at the API layer —
"not_applicable" would silently remove a control from the denominator, which
is the same as passing it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List

from backend.evidence.attestation import is_active
from backend.repositories.control_state_repo import attestation_repo, manual_status_repo
from backend.repositories.finding_repo import finding_repo

# Finding states that mean "remediation is not finished".
_OPEN_STATES = {"open", "assigned", "reopened"}
_WORKING_STATES = {"in_progress", "submitted_for_review"}

# Statuses a human may set directly.  Everything that improves the score must
# go through a finding approval, an attestation, or (later) an integration.
MANUAL_ALLOWED_STATUSES = frozenset({"fail", "unknown", "in_progress"})


def effective_statuses(org_id: str) -> Dict[str, Dict]:
    """Return {control_id: status_entry} in the shape calculate_score() expects."""
    now = datetime.now(timezone.utc)
    result: Dict[str, Dict] = {}

    # 5. Manual baseline
    for control_id, entry in manual_status_repo.get_all(org_id).items():
        result[control_id] = {**entry, "derived_from": "manual"}

    # 4. Active attestations
    for attest in attestation_repo.list_by_org(org_id):
        if not is_active(attest):
            continue
        for control_id in attest.control_ids:
            result[control_id] = {
                "status": "pass",
                "evidence_source": "attested_third_party",
                "notes": f"Attested: {attest.source_name}",
                "last_checked": attest.created_at,
                "derived_from": "attestation",
                "attestation_id": attest.id,
            }

    # 1–3. Findings (override attestations and manual state)
    by_control: Dict[str, List] = {}
    for finding in finding_repo.list_by_org(org_id):
        for control_id in finding.control_ids:
            by_control.setdefault(control_id, []).append(finding)

    for control_id, findings in by_control.items():
        open_work = [
            f for f in findings
            if f.state in _OPEN_STATES or f.state in _WORKING_STATES or f.risk_acceptance_expired(now)
        ]
        accepted = [f for f in findings if f.state == "risk_accepted" and not f.risk_acceptance_expired(now)]
        closed = [f for f in findings if f.state == "closed"]

        if open_work:
            working = any(f.state in _WORKING_STATES for f in open_work)
            result[control_id] = {
                "status": "in_progress" if working else "fail",
                "evidence_source": "manual",
                "notes": f"Open finding: {open_work[0].title}",
                "last_checked": max(f.updated_at for f in open_work),
                "derived_from": "finding",
                "finding_ids": [f.finding_id for f in open_work],
            }
        elif accepted:
            result[control_id] = {
                "status": "fail",
                "evidence_source": "manual",
                "notes": f"Risk accepted until {accepted[0].risk_accepted_until}",
                "last_checked": max(f.updated_at for f in accepted),
                "derived_from": "risk_acceptance",
                "risk_accepted": True,
                "finding_ids": [f.finding_id for f in accepted],
            }
        elif closed:
            result[control_id] = {
                "status": "pass",
                "evidence_source": "manual",
                "notes": f"Remediated and approved: {closed[-1].title}",
                "last_checked": max(f.updated_at for f in closed),
                "derived_from": "approved_finding",
                "finding_ids": [f.finding_id for f in closed],
            }

    return result

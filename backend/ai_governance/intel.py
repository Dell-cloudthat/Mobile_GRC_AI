"""
Product intelligence for one discovered AI app: what it is, why this team is
probably using it, what to do about it, and the MSP conversation it opens.

"Why" is an inference from the app's category and the departments of the
people using it.  It is labeled as inferred everywhere it's shown.
"""

from __future__ import annotations

from collections import Counter
from typing import Dict, List, Optional

from backend.ai_governance import catalog


def _lower_first(text: str) -> str:
    return text[:1].lower() + text[1:] if text else text


def department_breakdown(users: List[Dict]) -> List[Dict]:
    counts = Counter(u.get("department") or "Unknown" for u in users)
    return [{"department": d, "users": n} for d, n in counts.most_common()]


def likely_use(app: Optional[Dict], users: List[Dict]) -> Dict:
    cat = catalog.category(app["category"] if app else "general_assistant")
    reasons = cat["reasons"]
    breakdown = department_breakdown(users)
    known = [b for b in breakdown if b["department"] not in ("Unknown", "Other")]
    total = sum(b["users"] for b in breakdown)

    by_dept = [
        {"department": b["department"], "users": b["users"], "reason": reasons.get(b["department"], reasons["default"])}
        for b in known[:4]
    ]
    if known:
        top = known[0]
        headline = (f"Most likely: {_lower_first(reasons.get(top['department'], reasons['default']))} "
                    f"({top['users']} of {total} users are in {top['department']})")
    else:
        headline = f"Most likely: {_lower_first(reasons['default'])}"
    if app is None:
        headline = "Unknown vendor. " + headline.replace("Most likely", "If it's an AI assistant, most likely")
    return {
        "headline": headline,
        "underlying_need": cat["underlying_need"],
        "by_department": by_dept,
        "basis": "Inferred from the app's category and the departments of the people using it.",
    }


def _email_platform(profile: Dict) -> Optional[str]:
    provider = (profile.get("email_provider") or "").lower()
    clouds = " ".join(profile.get("cloud_providers") or []).lower()
    if "microsoft" in provider or "outlook" in provider or "office" in provider or "microsoft" in clouds:
        return "microsoft"
    if "google" in provider or "gmail" in provider or "google" in clouds:
        return "google"
    return None


def alternatives(app: Optional[Dict], profile: Dict) -> List[Dict]:
    """Safer options, starting with an assistant the client may already pay for."""
    out: List[Dict] = []
    seen = set()
    app_id = app["id"] if app else None
    platform = _email_platform(profile)
    category = app["category"] if app else "general_assistant"

    if platform and category in {"general_assistant", "writing_assistant", "research_search", "meeting_assistant", "presentation_design"}:
        inc = catalog.included_assistants()[platform]
        if inc["app_id"] != app_id:
            out.append({"app_id": inc["app_id"], "name": inc["name"], "why": inc["detail"], "already_licensed": True})
            seen.add(inc["app_id"])

    if app and app["tiers"].get("business"):
        biz = app["tiers"]["business"]
        out.append({
            "app_id": app_id, "name": f"{app['name']} {biz['label']}",
            "why": "Same tool on the business plan: company sign-in and admin controls"
                   + ("; doesn't train on your data." if biz.get("trains_on_inputs") == "no" else "; confirm its data terms."),
            "already_licensed": False,
        })
        seen.add(app_id)

    for alt_id in (app or {}).get("alternatives", []):
        if alt_id in seen:
            continue
        alt = catalog.get(alt_id)
        if not alt:
            continue
        biz = alt["tiers"].get("business")
        out.append({
            "app_id": alt_id,
            "name": f"{alt['name']} {biz['label']}" if biz else alt["name"],
            "why": alt["summary"],
            "already_licensed": False,
        })
        seen.add(alt_id)
    return out[:3]


def recommended_action(app: Optional[Dict], risk: Dict, status: str) -> Dict:
    level = risk["level"]
    keys = {f["key"] for f in risk["factors"]}
    if status == "blocked":
        return {"action": "confirm_removed", "label": "Confirm it's removed",
                "detail": "Revoke the app's Microsoft 365 / Google consent and check it doesn't show up in the next scan."}
    if status in ("approved", "approved_business"):
        return {"action": "none", "label": "Approved",
                "detail": "Keep it on the approved-tools list and review it at the next policy review."}
    if app is None:
        return {"action": "review", "label": "Review the vendor",
                "detail": "Find out what it is and what data it stores, then approve or block it."}
    if "restricted_jurisdiction" in keys or "not_for_business" in keys:
        return {"action": "block", "label": "Block and offer an alternative",
                "detail": "Revoke access, tell the users why, and point them to an approved tool."}
    if level in ("critical", "high"):
        if app["tiers"].get("business"):
            return {"action": "move_to_business", "label": "Move users to a business plan",
                    "detail": "Put these users on the business plan (or an assistant you already license), "
                              "then revoke personal-account access."}
        return {"action": "block", "label": "Block and offer an alternative",
                "detail": "There's no business plan to move to; replace it with an approved tool."}
    if level == "medium":
        return {"action": "review", "label": "Approve with conditions or move to business plan",
                "detail": "Approve it under the AI acceptable-use policy, or standardize on the business plan."}
    return {"action": "approve", "label": "Approve",
            "detail": "Low risk. Add it to the approved-tools list."}


def msp_opportunity(app: Optional[Dict]) -> str:
    return catalog.category(app["category"] if app else "general_assistant")["msp_opportunity"]

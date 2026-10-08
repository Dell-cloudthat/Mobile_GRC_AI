"""
Assemble the AI inventory (list + summary) and one app's detail view from
observations, decisions and the org profile.  Pure functions: the API and the
demo-data generator both call these.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from backend.ai_governance import catalog, intel, risk
from backend.ai_governance.matcher import is_unlisted

DECISIONS = {
    "approved": "Approved",
    "approved_business": "Approved on business plan",
    "under_review": "Under review",
    "blocked": "Blocked",
    "risk_accepted": "Risk accepted",
}
LEVEL_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
OPEN_STATUSES = {"unreviewed", "under_review"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def latest_decisions(history: List[Dict]) -> Dict[str, Dict]:
    """history is chronological; the last record per app wins."""
    out: Dict[str, Dict] = {}
    for d in history:
        out[d["app_key"]] = d
    return out


def status_of(decision: Optional[Dict], now: str) -> str:
    if not decision:
        return "unreviewed"
    if decision["decision"] == "risk_accepted" and decision.get("expires_at") and decision["expires_at"] <= now:
        return "unreviewed"
    return decision["decision"]


def _app_and_name(obs: Dict):
    app = None if is_unlisted(obs["app_key"]) else catalog.get(obs["app_key"])
    return app, (app["name"] if app else obs["display_name"])


def _evaluate(obs: Dict, profile: Dict, decision: Optional[Dict], now: str) -> Dict:
    app, name = _app_and_name(obs)
    status = status_of(decision, now)
    plan = risk.effective_plan(app, obs, decision["decision"] if decision and status != "unreviewed" else None)
    rk = risk.compute(app, obs, profile, plan=plan)
    return {"app": app, "name": name, "status": status, "risk": rk}


def _public_decision(d: Optional[Dict]) -> Optional[Dict]:
    if not d:
        return None
    return {
        "decision": d["decision"],
        "label": DECISIONS.get(d["decision"], d["decision"]),
        "note": d.get("note"),
        "expires_at": d.get("expires_at"),
        "decided_by_name": d.get("decided_by_name"),
        "decided_at": d.get("decided_at"),
    }


def build_item(obs: Dict, profile: Dict, decision: Optional[Dict], now: Optional[str] = None) -> Dict:
    now = now or _now_iso()
    ev = _evaluate(obs, profile, decision, now)
    app, rk, status = ev["app"], ev["risk"], ev["status"]
    cat = catalog.category(app["category"] if app else "general_assistant")
    still_in_use = bool(status == "blocked" and decision and obs.get("last_seen") and obs["last_seen"] > decision["decided_at"])
    return {
        "app_key": obs["app_key"],
        "name": ev["name"],
        "vendor": app["vendor"] if app else None,
        "category": app["category"] if app else None,
        "category_label": cat["label"] if app else "Possible AI app (not in catalog)",
        "listed": app is not None,
        "user_count": obs.get("user_count") or 0,
        "departments": intel.department_breakdown(obs.get("users") or [])[:3],
        "sources": obs.get("sources") or [],
        "first_seen": obs.get("first_seen"),
        "last_seen": obs.get("last_seen"),
        "admin_consented": "AllPrincipals" in (obs.get("consent_types") or []),
        "risk": {
            "score": rk["score"], "level": rk["level"], "plan_assumed": rk["plan_assumed"],
            "plan_label": rk["plan_label"], "top_factors": [f["label"] for f in rk["factors"][:3]],
        },
        "status": status,
        "status_label": DECISIONS.get(status, "Not reviewed"),
        "decision": _public_decision(decision) if status != "unreviewed" else None,
        "decision_expired": bool(decision and decision["decision"] == "risk_accepted" and status == "unreviewed"),
        "still_in_use": still_in_use,
        "likely_use": intel.likely_use(app, obs.get("users") or [])["headline"],
        "recommended_action": intel.recommended_action(app, rk, status),
    }


def build_inventory(observations: List[Dict], decision_history: List[Dict], profile: Dict,
                    now: Optional[str] = None) -> Dict:
    now = now or _now_iso()
    latest = latest_decisions(decision_history)
    items = [build_item(o, profile, latest.get(o["app_key"]), now) for o in observations]
    items.sort(key=lambda i: (i["status"] not in OPEN_STATUSES, LEVEL_ORDER[i["risk"]["level"]],
                              -i["risk"]["score"], -i["user_count"], i["name"].lower()))

    people = {u["user"] for o in observations for u in o.get("users") or []}
    dept_people: Dict[str, set] = {}
    for o in observations:
        for u in o.get("users") or []:
            dept_people.setdefault(u.get("department") or "Unknown", set()).add(u["user"])
    by_level = {lvl: 0 for lvl in LEVEL_ORDER}
    for i in items:
        by_level[i["risk"]["level"]] += 1
    needs = [i for i in items if i["status"] in OPEN_STATUSES and i["risk"]["level"] in ("critical", "high")]
    regulated = [risk.REGULATED_DATA[d] for d in profile.get("sensitive_data", []) if d in risk.REGULATED_DATA]

    return {
        "summary": {
            "apps": len(items),
            "people": len(people) or sum(i["user_count"] for i in items),
            "by_level": by_level,
            "needs_attention": len(needs),
            "unreviewed": sum(1 for i in items if i["status"] in OPEN_STATUSES),
            "approved": sum(1 for i in items if i["status"] in ("approved", "approved_business")),
            "blocked": sum(1 for i in items if i["status"] == "blocked"),
            "still_in_use_after_block": sum(1 for i in items if i["still_in_use"]),
            "unlisted": sum(1 for i in items if not i["listed"]),
            "top_departments": sorted(
                ({"department": d, "people": len(p)} for d, p in dept_people.items() if d != "Unknown"),
                key=lambda x: -x["people"])[:4],
            "regulated_data": regulated,
            "last_seen": max((o.get("last_seen") for o in observations if o.get("last_seen")), default=None),
            "top_risk": needs[0]["name"] if needs else None,
        },
        "apps": items,
        "catalog_reviewed_at": catalog.reviewed_at(),
        "disclaimer": catalog.disclaimer(),
    }


def build_detail(obs: Dict, decision_history: List[Dict], profile: Dict, *, include_users: bool = True,
                 now: Optional[str] = None) -> Dict:
    now = now or _now_iso()
    history = [d for d in decision_history if d["app_key"] == obs["app_key"]]
    latest = history[-1] if history else None
    item = build_item(obs, profile, latest, now)
    ev = _evaluate(obs, profile, latest, now)
    app, rk = ev["app"], ev["risk"]

    risk_if_business = None
    if app and app["tiers"].get("business") and rk["plan_assumed"] == "consumer":
        rb = risk.compute(app, obs, profile, plan="business")
        risk_if_business = {"score": rb["score"], "level": rb["level"], "plan_label": rb["plan_label"]}

    return {
        **item,
        "app": catalog.public_app(app) if app else None,
        "risk_factors": rk["factors"],
        "risk_if_business": risk_if_business,
        "likely_use": intel.likely_use(app, obs.get("users") or []),
        "alternatives": intel.alternatives(app, profile),
        "msp_opportunity": intel.msp_opportunity(app),
        "evidence": {
            "raw_names": obs.get("raw_names") or [],
            "domains": obs.get("domains") or [],
            "scopes": obs.get("scopes") or [],
            "consent_types": obs.get("consent_types") or [],
        },
        "users": (obs.get("users") or []) if include_users else None,
        "decision_history": [_public_decision(d) for d in reversed(history)],
        "catalog_reviewed_at": catalog.reviewed_at(),
        "disclaimer": catalog.disclaimer(),
    }


def portfolio_rollup(entries: List[Tuple[str, str, Dict]]) -> Dict:
    """
    MSP view across clients.  entries: (org_id, org_name, inventory) per client.
    Returns per-client summaries, the apps seen at the most clients, and the
    service offers the open high-risk findings point to.
    """
    clients: List[Dict] = []
    app_clients: Dict[str, set] = defaultdict(set)
    app_names: Dict[str, str] = {}
    opportunity_clients: Dict[str, set] = defaultdict(set)
    level_totals: Counter = Counter()

    for org_id, name, inv in entries:
        s = inv["summary"]
        for item in inv["apps"]:
            app_clients[item["app_key"]].add(org_id)
            app_names[item["app_key"]] = item["name"]
            level_totals[item["risk"]["level"]] += 1
            if item["status"] in OPEN_STATUSES and item["risk"]["level"] in ("critical", "high"):
                opportunity_clients[item["category"] or "general_assistant"].add(org_id)
        clients.append({
            "org_id": org_id,
            "name": name,
            "apps": s["apps"],
            "people": s["people"] if s["apps"] else 0,
            "needs_attention": s["needs_attention"],
            "critical": s["by_level"]["critical"],
            "top_risk": s["top_risk"],
            "last_seen": s["last_seen"],
            "scanned": s["apps"] > 0,
        })

    clients.sort(key=lambda c: (-c["needs_attention"], -c["critical"], c["name"].lower()))
    top_apps = sorted(
        ({"app_key": k, "name": app_names[k], "clients": len(v)} for k, v in app_clients.items()),
        key=lambda a: (-a["clients"], a["name"].lower()),
    )[:8]
    opportunities = sorted(
        ({"category": c, "label": catalog.category(c)["label"], "clients": len(v),
          "offer": catalog.category(c)["msp_opportunity"]} for c, v in opportunity_clients.items()),
        key=lambda o: (-o["clients"], o["label"]),
    )
    return {
        "clients": clients,
        "totals": {
            "clients": len(entries),
            "clients_scanned": sum(1 for c in clients if c["scanned"]),
            "apps": sum(c["apps"] for c in clients),
            "needs_attention": sum(c["needs_attention"] for c in clients),
            "by_level": {lvl: level_totals.get(lvl, 0) for lvl in ("critical", "high", "medium", "low")},
        },
        "top_apps": top_apps,
        "opportunities": opportunities,
    }

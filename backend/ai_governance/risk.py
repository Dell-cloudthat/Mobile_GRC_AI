"""
Explainable risk score (0–100, higher is riskier) for one AI app in one org.

Every point comes from a named factor the UI shows, so an MSP can explain the
number to a client.  Unknowns score as a gap, never as safe.

Inputs:
  app          — catalog entry, or None for an unlisted app
  observation  — what discovery saw (users, scopes, sources)
  profile      — org profile (sensitive data types, email provider)
  plan         — "consumer" (default assumption) or "business" (when the org
                 has approved the business plan)
"""

from __future__ import annotations

from typing import Dict, List, Optional

from backend.ai_governance import catalog

LEVELS = (("critical", 70), ("high", 50), ("medium", 30), ("low", 0))

REGULATED_DATA = {
    "phi": "patient health information (HIPAA)",
    "payment": "payment card data (PCI DSS)",
    "federal": "federal / government data (CMMC)",
    "children": "children's data (COPPA)",
    "legal": "confidential legal documents",
    "financial": "financial records",
}

RESTRICTED_JURISDICTIONS = {"CN": "China", "RU": "Russia", "IR": "Iran", "KP": "North Korea"}

# ── Microsoft Graph delegated scopes → what the app can reach ────────────────

_BASIC = {"openid", "profile", "email", "user.read", "offline_access", "user.readbasic.all"}


def classify_scopes(scopes: List[str]) -> List[Dict]:
    """Return exposure findings (highest first) for a list of OAuth scopes."""
    s = {x.strip().lower() for x in scopes if x and x.strip()}
    out: List[Dict] = []

    def add(points: int, key: str, label: str) -> None:
        out.append({"key": key, "points": points, "label": label})

    org_wide = sorted(x for x in s if x.endswith(".all") and x not in _BASIC
                      and x.split(".")[0] in {"files", "sites", "mail", "directory", "user", "group",
                                               "chat", "channelmessage", "notes", "calendars"})
    if org_wide:
        add(25, "scope_org_wide", f"Can read data across the whole organization ({', '.join(org_wide[:3])})")
    if any(x.startswith("mail.") for x in s):
        add(20, "scope_mail", "Can read or send email from users' mailboxes")
    if any(x.startswith(("chat.", "channelmessage.")) for x in s):
        add(15, "scope_chat", "Can read Teams chats")
    if any(x.startswith(("files.", "sites.", "notes.")) for x in s) and not org_wide:
        add(12, "scope_files", "Can read users' OneDrive / SharePoint files")
    if any(x.startswith(("calendars.", "onlinemeeting", "onlinemeetings", "onlinemeetingtranscript")) for x in s):
        add(12, "scope_meetings", "Can read calendars and join or transcribe meetings")
    if "offline_access" in s and out:
        add(3, "scope_offline", "Keeps access even when the user isn't signed in")
    out.sort(key=lambda f: -f["points"])
    return out


def effective_plan(app: Optional[Dict], observation: Dict, decision: Optional[str]) -> str:
    """
    Which plan to score against.  Default is the consumer plan (we can't see
    billing).  Business when the org approved the business plan, or when the
    app was seen through a work-account consent for apps whose work-account
    version IS the business version (Microsoft 365 Copilot Chat, Gemini in
    Workspace).
    """
    if not app or not app["tiers"].get("business"):
        return "consumer"
    if decision == "approved_business":
        return "business"
    if "work_account_means_business" in app.get("flags", []) and observation.get("consent_types"):
        return "business"
    return "consumer"


def _level(score: int) -> str:
    for name, floor in LEVELS:
        if score >= floor:
            return name
    return "low"


def compute(app: Optional[Dict], observation: Dict, profile: Optional[Dict] = None, plan: str = "consumer") -> Dict:
    profile = profile or {}
    factors: List[Dict] = []

    def add(points: int, key: str, label: str, detail: Optional[str] = None) -> None:
        if points:
            factors.append({"key": key, "points": points, "label": label, "detail": detail})

    tier = None
    if app is None:
        add(20, "unlisted", "Not in our AI catalog yet",
            "We haven't reviewed this vendor. Treat it as untrusted until someone checks its data terms.")
    else:
        tiers = app["tiers"]
        tier_key = "business" if plan == "business" and tiers.get("business") else "consumer"
        tier = tiers[tier_key]
        plan_label = f"{tier['label']} plan"
        trains = tier.get("trains_on_inputs", "unknown")
        if trains == "yes":
            add(25, "trains_yes", f"Uses your data to train AI models ({plan_label})",
                "What employees type or upload can become training data for the vendor's models.")
        elif trains == "opt_out":
            add(20, "trains_opt_out", f"Trains on your data unless each person opts out ({plan_label})",
                "Opt-out is per person and can't be enforced centrally on this plan.")
        elif trains == "unknown":
            add(12, "trains_unknown", f"Not confirmed whether it trains on your data ({plan_label})",
                "Check the vendor's terms before approving.")
        if not tier.get("admin_controls"):
            add(8, "no_admin_controls", "No company admin controls",
                "You can't enforce settings, see usage, or remove access when someone leaves.")
        if tiers.get("business") is None:
            add(5, "no_business_plan", "No business plan available",
                "There is no version with company controls to move people onto.")
        hq = app.get("hq_country")
        if hq in RESTRICTED_JURISDICTIONS:
            add(30, "restricted_jurisdiction", f"Data held in {RESTRICTED_JURISDICTIONS[hq]}",
                "Subject to that country's data access laws; often prohibited by government and regulated-industry contracts.")
        soc2 = app.get("soc2")
        if soc2 is False:
            add(10, "no_soc2", "No SOC 2 report")
        elif soc2 is None:
            add(6, "soc2_unknown", "SOC 2 report not confirmed")
        flags = set(app.get("flags", []))
        if "not_for_business" in flags:
            add(10, "not_for_business", "Consumer app, not meant for work data")
        if "public_by_default" in flags:
            add(10, "public_by_default", "Creations are public by default on lower plans")
        if "records_without_bot" in flags:
            add(8, "records_without_bot", "Transcribes meetings with no visible bot",
                "Other attendees may not know they're being recorded; some states require all-party consent.")
        if "auto_joins_meetings" in flags:
            add(5, "auto_joins_meetings", "Joins meetings automatically and spreads to attendees")
        if "routes_to_third_party_models" in flags:
            add(6, "third_party_models", "Sends chats to other AI vendors and community bots")
        if "voice_or_likeness_cloning" in flags:
            add(5, "cloning", "Can clone voices or likenesses", "A cloned executive voice is a known fraud tool.")
        if "holds_credentials" in flags:
            add(6, "holds_credentials", "Stores logins to your other business systems")

    # What the app can reach: real OAuth scopes beat category assumptions.
    scope_findings = classify_scopes(observation.get("scopes") or [])
    if scope_findings:
        for f in scope_findings:
            add(f["points"], f["key"], f["label"], "Granted through Microsoft 365 consent.")
    else:
        exposure = catalog.category(app["category"] if app else "general_assistant")["default_exposure"]
        add(exposure["points"], "exposure_default", exposure["label"])

    users = int(observation.get("user_count") or 0)
    if users >= 25:
        add(8, "breadth", f"Used by {users} people")
    elif users >= 10:
        add(5, "breadth", f"Used by {users} people")

    regulated = [REGULATED_DATA[d] for d in profile.get("sensitive_data", []) if d in REGULATED_DATA]
    risky_handling = any(f["key"] in {"trains_yes", "trains_opt_out", "trains_unknown", "unlisted",
                                      "restricted_jurisdiction", "scope_org_wide", "scope_mail"} for f in factors)
    if regulated and risky_handling:
        add(10, "regulated_data", f"Your business handles {regulated[0]}",
            "Putting regulated data into a tool without a signed data agreement (such as a HIPAA BAA) "
            "can be an impermissible disclosure.")

    score = min(100, sum(f["points"] for f in factors))
    factors.sort(key=lambda f: -f["points"])
    return {
        "score": score,
        "level": _level(score),
        "plan_assumed": plan if (app and plan == "business" and app["tiers"].get("business")) else "consumer",
        "plan_label": tier["label"] if tier else None,
        "factors": factors,
    }

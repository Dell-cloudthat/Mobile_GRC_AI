"""
Generate apps/web/src/data/aiDemo.json: the AI Usage demo dataset.

Everything in it comes from the real engine (import → risk → intelligence),
run on sample client exports with a fixed clock, so the demo shows exactly
what connected mode would show.  Regenerate after changing the catalog or
the engine (a test fails if it's stale):

    python -m backend.scripts.build_ai_demo
"""

from __future__ import annotations

import json
import pathlib
from typing import Dict

from backend.ai_governance import catalog, importers, risk, service
from backend.ai_governance.observations import merge

NOW = "2026-10-08T12:00:00+00:00"
ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = ROOT / "apps" / "web" / "src" / "data" / "aiDemo.json"
SAMPLE = pathlib.Path(__file__).resolve().parents[1] / "ai_governance" / "sample_data" / "demo_tenant.csv"

CLIENTS = [
    {
        "org_id": "demo-riverside", "name": "Riverside Health",
        "profile": {"email_provider": "Microsoft 365 (Outlook)", "sensitive_data": ["phi", "pii"]},
        "csv": SAMPLE.read_text(),
    },
    {
        "org_id": "demo-bolt", "name": "Bolt Logistics",
        "profile": {"email_provider": "Google Workspace (Gmail)", "sensitive_data": ["pii", "financial"]},
        "csv": "App,User,Department,LastSignIn\n" + "".join(
            f"{app},{u}@bolt.example,{d},2026-10-0{i % 7 + 1}T10:00:00Z\n"
            for i, (app, u, d) in enumerate([
                ("ChatGPT", "ana", "Operations"), ("ChatGPT", "bo", "Dispatch Operations"), ("ChatGPT", "cy", "Sales"),
                ("ChatGPT", "di", "Sales"), ("ChatGPT", "ed", "Finance"), ("ChatGPT", "fay", "Customer Support"),
                ("Read AI", "gus", "Sales"), ("Read AI", "hal", "Leadership"),
                ("Zapier", "ana", "Operations"), ("Zapier", "ira", "Finance"),
                ("Grammarly", "fay", "Customer Support"), ("Grammarly", "jo", "Marketing"), ("Grammarly", "cy", "Sales"),
                ("Gemini", "kim", "Marketing"),
            ])),
    },
    {
        "org_id": "demo-cedar", "name": "Cedar Law Group",
        "profile": {"email_provider": "Microsoft 365 (Outlook)", "sensitive_data": ["legal", "pii"]},
        "csv": "App,User,Department,LastSignIn\n" + "".join(
            f"{app},{u}@cedarlaw.example,{d},2026-10-0{i % 7 + 1}T15:00:00Z\n"
            for i, (app, u, d) in enumerate([
                ("Claude", "amy", "Legal"), ("Claude", "ben", "Legal"), ("Claude", "cal", "Paralegal"),
                ("Otter.ai", "amy", "Legal"), ("Otter.ai", "dee", "Legal"), ("Otter.ai", "eli", "Client Services"),
                ("Otter.ai", "fox", "Executive"),
                ("ChatPDF", "ben", "Legal"), ("ChatPDF", "cal", "Paralegal"),
                ("Granola", "fox", "Executive"),
            ])),
    },
]


def _observations(csv_text: str):
    result = importers.parse_csv(csv_text, now=NOW)
    return [merge(None, o, updated_at=NOW) for o in result.observations]


def build() -> Dict:
    entries = []
    primary = None
    for c in CLIENTS:
        obs = _observations(c["csv"])
        inv = service.build_inventory(obs, [], c["profile"], now=NOW)
        entries.append((c["org_id"], c["name"], inv))
        if primary is None:
            details = {}
            business_risk = {}
            for o in obs:
                details[o["app_key"]] = service.build_detail(o, [], c["profile"], now=NOW)
                app = catalog.get(o["app_key"])
                if app and app["tiers"].get("business"):
                    rb = risk.compute(app, o, c["profile"], plan="business")
                    business_risk[o["app_key"]] = {
                        "score": rb["score"], "level": rb["level"], "plan_assumed": "business",
                        "plan_label": rb["plan_label"], "top_factors": [f["label"] for f in rb["factors"][:3]],
                        "factors": rb["factors"],
                    }
            primary = {"org_name": c["name"], "profile": c["profile"], "inventory": inv,
                       "details": details, "business_risk": business_risk}
    return {"generated_from": "backend/scripts/build_ai_demo.py", "now": NOW, **primary,
            "msp_rollup": service.portfolio_rollup(entries)}


if __name__ == "__main__":
    OUT.write_text(json.dumps(build(), indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size // 1024} KB)")

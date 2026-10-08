"""
Shadow AI v1 — discovery, risk, intelligence, decisions, MSP rollup.

Runs in memory by default and against Postgres with TEST_DATABASE_URL.
"""

import json
import pathlib
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from backend import db
from backend.ai_governance import catalog, importers, intel, matcher, risk
from backend.ai_governance.observations import merge
from backend.integrations import m365_ai_discovery as m365
from backend.tests.conftest import API, add_member, auth, create_org, future_iso, invite_and_accept, make_token

pg_only = pytest.mark.skipif(not db.is_enabled(), reason="needs TEST_DATABASE_URL (Postgres)")
SAMPLE = (pathlib.Path(__file__).resolve().parents[1] / "ai_governance" / "sample_data" / "demo_tenant.csv").read_text()
REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


# ══════════════════════════════════════════════════════════════════════════════
# Catalog integrity
# ══════════════════════════════════════════════════════════════════════════════

def test_catalog_entries_are_well_formed():
    ids = [a["id"] for a in catalog.apps()]
    assert len(ids) == len(set(ids)), "duplicate app ids"
    cats = catalog.categories()
    for a in catalog.apps():
        assert a["category"] in cats, a["id"]
        assert a["tiers"]["consumer"]["trains_on_inputs"] in {"yes", "no", "opt_out", "unknown"}, a["id"]
        biz = a["tiers"].get("business")
        if biz:
            assert biz["trains_on_inputs"] in {"yes", "no", "opt_out", "unknown"}, a["id"]
        assert a.get("soc2") in (True, False, None), a["id"]
        for alt in a.get("alternatives", []):
            assert catalog.get(alt), f"{a['id']} → unknown alternative {alt}"
        assert a["match"]["names"] or a["match"]["domains"], a["id"]
    for c in cats.values():
        assert "default" in c["reasons"] and c["msp_opportunity"] and c["underlying_need"]


def test_demo_dataset_is_up_to_date():
    """apps/web/src/data/aiDemo.json is generated from the engine — regenerate when the engine changes."""
    from backend.scripts.build_ai_demo import build
    web = REPO_ROOT / "apps" / "web" / "src" / "data" / "aiDemo.json"
    assert json.loads(web.read_text()) == build(), "Run: python -m backend.scripts.build_ai_demo"


# ══════════════════════════════════════════════════════════════════════════════
# Matching
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("kwargs,expected", [
    ({"name": "ChatGPT"}, "chatgpt"),
    ({"domain": "https://chat.openai.com/c/123"}, "chatgpt"),
    ({"domain": "www.perplexity.ai"}, "perplexity"),
    ({"name": "Otter.ai Notetaker"}, "otter"),
    ({"name": "GitHub Copilot for Business"}, "github_copilot"),   # not taken for Microsoft Copilot
    ({"name": "Microsoft 365 Copilot"}, "microsoft_copilot"),
    ({"name": "Fireflies.ai Notetaker"}, "fireflies"),
    ({"domain": "chat.deepseek.com"}, "deepseek"),
])
def test_matcher_finds_catalog_apps(kwargs, expected):
    m = matcher.match(**kwargs)
    assert m and m.listed and m.app_key == expected


def test_matcher_keeps_unknown_ai_apps_and_ignores_the_rest():
    m = matcher.match(name="AI Meeting Notes Pro")
    assert m and not m.listed and m.app_key == "unlisted:ai-meeting-notes-pro" and m.confidence == "low"
    assert matcher.match(name="Adobe Acrobat") is None
    assert matcher.match(name="DocuSign") is None
    assert matcher.match(name="Mailchimp") is None


def test_department_normalization():
    assert catalog.normalize_department("Inside Sales - East") == "Sales"
    assert catalog.normalize_department("People Operations") == "HR"
    assert catalog.normalize_department("Clinical - Nursing") == "Clinical"
    assert catalog.normalize_department("Software Engineering") == "Engineering"
    assert catalog.normalize_department("Underwater Basket Weaving") == "Other"
    assert catalog.normalize_department("") is None


# ══════════════════════════════════════════════════════════════════════════════
# Import + merge
# ══════════════════════════════════════════════════════════════════════════════

def test_import_sample_tenant():
    r = importers.parse_csv(SAMPLE)
    keys = {o["app_key"] for o in r.observations}
    assert {"chatgpt", "otter", "deepseek", "perplexity", "zapier", "unlisted:ai-meeting-notes-pro"} <= keys
    assert r.ignored_samples == ["Adobe Acrobat", "DocuSign"]
    chatgpt = next(o for o in r.observations if o["app_key"] == "chatgpt")
    assert len(chatgpt["users"]) == 10
    assert {"Sales", "Marketing", "Clinical"} <= {u["department"] for u in chatgpt["users"]}
    assert r.columns["name"] == "App" and r.columns["user"] == "User"


def test_import_per_app_rows_with_user_counts():
    r = importers.parse_csv("Name,Users,Domain\nChatGPT,42,chatgpt.com\nSlack,300,slack.com\n")
    assert [o["app_key"] for o in r.observations] == ["chatgpt"]
    assert r.observations[0]["reported_user_count"] == 42


def test_import_rejects_files_without_app_columns():
    with pytest.raises(importers.ImportError_) as exc:
        importers.parse_csv("Foo,Bar\n1,2\n")
    assert "app name or domain" in str(exc.value)


def test_merge_unions_users_and_keeps_departments():
    a = {"app_key": "chatgpt", "display_name": "ChatGPT", "listed": True, "sources": ["csv"],
         "users": [{"user": "a@x", "department": "Sales"}], "scopes": ["openid"], "first_seen": "2026-01-01T00:00:00+00:00",
         "last_seen": "2026-01-02T00:00:00+00:00"}
    b = {**a, "users": [{"user": "a@x", "department": None}, {"user": "b@x", "department": "HR"}],
         "scopes": ["Mail.Read"], "last_seen": "2026-02-01T00:00:00+00:00", "sources": ["m365"]}
    m = merge(merge(None, a, updated_at="t"), b, updated_at="t2")
    assert m["user_count"] == 2
    assert {u["user"]: u["department"] for u in m["users"]} == {"a@x": "Sales", "b@x": "HR"}
    assert m["scopes"] == ["Mail.Read", "openid"] and m["sources"] == ["csv", "m365"]
    assert m["last_seen"] == "2026-02-01T00:00:00+00:00" and m["first_seen"] == "2026-01-01T00:00:00+00:00"


# ══════════════════════════════════════════════════════════════════════════════
# Risk + intelligence
# ══════════════════════════════════════════════════════════════════════════════

def _obs(**kw):
    base = {"app_key": "x", "users": [], "user_count": 1, "scopes": [], "consent_types": []}
    base.update(kw)
    return base


def test_deepseek_is_critical_because_of_jurisdiction():
    r = risk.compute(catalog.get("deepseek"), _obs())
    keys = [f["key"] for f in r["factors"]]
    assert r["level"] == "critical" and "restricted_jurisdiction" in keys and "trains_yes" in keys


def test_business_plan_lowers_chatgpt_risk():
    consumer = risk.compute(catalog.get("chatgpt"), _obs())
    business = risk.compute(catalog.get("chatgpt"), _obs(), plan="business")
    assert business["score"] < consumer["score"]
    assert "trains_opt_out" in {f["key"] for f in consumer["factors"]}
    assert not {"trains_opt_out", "no_admin_controls"} & {f["key"] for f in business["factors"]}


def test_real_scopes_drive_exposure():
    findings = risk.classify_scopes(["openid", "Mail.ReadWrite", "Files.ReadWrite.All", "offline_access"])
    keys = [f["key"] for f in findings]
    assert keys[0] == "scope_org_wide" and "scope_mail" in keys and "scope_offline" in keys
    assert risk.classify_scopes(["openid", "profile", "email", "User.Read", "offline_access"]) == []


def test_regulated_data_adds_risk_only_when_handling_is_risky():
    phi = {"sensitive_data": ["phi"]}
    assert "regulated_data" in {f["key"] for f in risk.compute(catalog.get("chatgpt"), _obs(), phi)["factors"]}
    assert "regulated_data" not in {f["key"] for f in risk.compute(catalog.get("canva_ai"), _obs(), phi)["factors"]}


def test_unknowns_score_as_gaps_not_as_safe():
    r = risk.compute(catalog.get("gamma"), _obs())
    keys = {f["key"] for f in r["factors"]}
    assert {"trains_unknown", "soc2_unknown"} <= keys


def test_copilot_on_work_account_counts_as_business():
    app = catalog.get("microsoft_copilot")
    assert risk.effective_plan(app, _obs(consent_types=["AllPrincipals"]), None) == "business"
    assert risk.effective_plan(app, _obs(), None) == "consumer"
    assert risk.effective_plan(catalog.get("chatgpt"), _obs(consent_types=["Principal"]), None) == "consumer"


def test_likely_use_reflects_departments():
    users = [{"user": f"s{i}", "department": "Sales"} for i in range(3)] + [{"user": "h", "department": "HR"}]
    lu = intel.likely_use(catalog.get("otter"), users)
    assert "3 of 4 users are in Sales" in lu["headline"] and "CRM" in lu["headline"]
    assert lu["by_department"][0]["department"] == "Sales"
    assert "Inferred" in lu["basis"]


def test_alternatives_lead_with_assistant_already_licensed():
    alts = intel.alternatives(catalog.get("chatgpt"), {"email_provider": "Microsoft 365 (Outlook)"})
    assert alts[0]["already_licensed"] and alts[0]["name"] == "Microsoft 365 Copilot Chat"
    g = intel.alternatives(catalog.get("chatgpt"), {"email_provider": "Google Workspace (Gmail)"})
    assert g[0]["name"] == "Gemini in Google Workspace"
    assert all(a["app_id"] != "microsoft_copilot" or a["already_licensed"] for a in alts)


def test_recommended_actions():
    deep = risk.compute(catalog.get("deepseek"), _obs())
    assert intel.recommended_action(catalog.get("deepseek"), deep, "unreviewed")["action"] == "block"
    otter = risk.compute(catalog.get("otter"), _obs(scopes=["Calendars.Read", "OnlineMeetings.Read"]), {"sensitive_data": ["phi"]})
    assert intel.recommended_action(catalog.get("otter"), otter, "unreviewed")["action"] == "move_to_business"
    assert intel.recommended_action(None, otter, "unreviewed")["action"] == "review"
    assert intel.recommended_action(catalog.get("otter"), otter, "blocked")["action"] == "confirm_removed"


# ══════════════════════════════════════════════════════════════════════════════
# API
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def ai(client):
    owner = make_token("ai-owner", name="Olivia Owner")
    org = create_org(client, owner, "Riverside Health", also_executive=True)
    client.post(f"{API}/organizations/{org}/profile", headers=auth(owner), json={
        "business_name": "Riverside Health", "industry": "Healthcare", "employee_count": "25–50",
        "email_provider": "Microsoft 365 (Outlook)", "cloud_providers": [], "sensitive_data": ["phi", "pii"],
    })
    add_member(client, owner, org, "ai-eng", "engineer")
    add_member(client, owner, org, "ai-aud", "auditor", expires_at=future_iso(30))
    admin_only = make_token("ai-admin2", name="Adam Admin")
    add_member(client, owner, org, "ai-admin2", "admin")
    exec2 = make_token("ai-exec2", name="Erin Exec")
    assert invite_and_accept(client, owner, org, "executive", exec2).status_code == 200
    return {"org": org, "owner": owner, "exec2": exec2, "admin": admin_only,
            "eng": make_token("ai-eng", name="Evan Eng"), "aud": make_token("ai-aud", name="Ava Auditor")}


def _import(client, ai, token=None, text=SAMPLE):
    return client.post(f"{API}/organizations/{ai['org']}/ai-apps/import",
                       json={"csv_text": text, "filename": "tenant.csv"}, headers=auth(token or ai["eng"]))


def test_import_permissions(client, ai):
    assert _import(client, ai, ai["aud"]).status_code == 403
    assert _import(client, ai, make_token("ai-stranger")).status_code == 404
    r = _import(client, ai)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["apps_found"] >= 14 and "AI Meeting Notes Pro" in body["possible_ai_apps"]
    assert body["ignored_rows"] == 3


def test_import_reports_bad_files(client, ai):
    r = _import(client, ai, text="Foo,Bar\n1,2\n")
    assert r.status_code == 422 and "app name or domain" in r.json()["detail"]


def test_inventory_summary_and_order(client, ai):
    r = client.get(f"{API}/organizations/{ai['org']}/ai-apps", headers=auth(ai["aud"]))
    assert r.status_code == 200, r.text
    inv = r.json()
    s = inv["summary"]
    assert s["apps"] >= 14 and s["people"] >= 20 and s["needs_attention"] >= 3
    assert s["regulated_data"][0].startswith("patient health information")
    assert inv["apps"][0]["risk"]["level"] == "critical"      # worst open item first
    assert inv["can_import"] is False and inv["can_decide"] is False
    names = [a["name"] for a in inv["apps"]]
    assert "DeepSeek" in names[:4]
    copilot = next(a for a in inv["apps"] if a["app_key"] == "microsoft_copilot")
    assert copilot["admin_consented"] and copilot["risk"]["plan_assumed"] == "business"


def test_detail_has_intel_users_and_alternatives(client, ai):
    r = client.get(f"{API}/organizations/{ai['org']}/ai-apps/otter", headers=auth(ai["eng"]))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["app"]["vendor"] == "Otter.ai" and d["likely_use"]["by_department"][0]["department"] == "Sales"
    assert d["alternatives"][0]["name"] == "Microsoft 365 Copilot Chat"
    assert d["risk_if_business"]["score"] < d["risk"]["score"]
    assert len(d["users"]) == 5 and "Calendars.Read" in d["evidence"]["scopes"]
    assert d["msp_opportunity"] and d["disclaimer"]
    assert client.get(f"{API}/organizations/{ai['org']}/ai-apps/nope", headers=auth(ai["eng"])).status_code == 404


def test_unlisted_app_detail(client, ai):
    r = client.get(f"{API}/organizations/{ai['org']}/ai-apps/unlisted:ai-meeting-notes-pro", headers=auth(ai["eng"]))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["listed"] is False and d["app"] is None
    assert d["recommended_action"]["action"] == "review" and "unlisted" in {f["key"] for f in d["risk_factors"]}


def _decide(client, ai, app_key, token, **body):
    return client.post(f"{API}/organizations/{ai['org']}/ai-apps/{app_key}/decision", json=body, headers=auth(token))


def test_only_executives_decide(client, ai):
    assert _decide(client, ai, "chatgpt", ai["eng"], decision="under_review").status_code == 403
    assert _decide(client, ai, "chatgpt", ai["admin"], decision="under_review").status_code == 403
    assert _decide(client, ai, "chatgpt", ai["aud"], decision="under_review").status_code == 403
    assert _decide(client, ai, "chatgpt", ai["exec2"], decision="under_review").status_code == 201


def test_approving_high_risk_as_is_needs_a_reason(client, ai):
    r = _decide(client, ai, "read_ai", ai["exec2"], decision="approved")
    assert r.status_code == 422 and "20 characters" in r.json()["detail"]
    r = _decide(client, ai, "read_ai", ai["exec2"], decision="approved",
                note="Signed vendor DPA; recordings limited to internal meetings")
    assert r.status_code == 201 and r.json()["status"] == "approved"


def test_approve_business_plan_rescoring(client, ai):
    before = client.get(f"{API}/organizations/{ai['org']}/ai-apps/chatgpt", headers=auth(ai["owner"])).json()
    r = _decide(client, ai, "chatgpt", ai["owner"], decision="approved_business", note="Moving staff to ChatGPT Business")
    assert r.status_code == 201, r.text
    after = r.json()
    assert after["status"] == "approved_business" and after["risk"]["plan_assumed"] == "business"
    assert after["risk"]["score"] < before["risk"]["score"]
    assert after["decision_history"][0]["decision"] == "approved_business"
    assert after["decision_history"][1]["decision"] == "under_review"
    assert _decide(client, ai, "unlisted:ai-meeting-notes-pro", ai["owner"],
                   decision="approved_business").status_code == 422
    assert _decide(client, ai, "deepseek", ai["owner"], decision="approved_business").status_code == 422


def test_risk_acceptance_rules(client, ai):
    org = ai["org"]
    assert _decide(client, ai, "zapier", ai["owner"], decision="risk_accepted", note="short",
                   expires_at=future_iso(30)).status_code == 422
    assert _decide(client, ai, "zapier", ai["owner"], decision="risk_accepted",
                   note="Ops automation needed until the Copilot Studio rollout").status_code == 422
    r = _decide(client, ai, "zapier", ai["owner"], decision="risk_accepted",
                note="Ops automation needed until the Copilot Studio rollout", expires_at=future_iso(120))
    assert r.status_code == 422 and "90 days" in r.json()["detail"]            # zapier is critical here
    r = _decide(client, ai, "zapier", ai["owner"], decision="risk_accepted",
                note="Ops automation needed until the Copilot Studio rollout", expires_at=future_iso(60))
    assert r.status_code == 201 and r.json()["status"] == "risk_accepted"
    inv = client.get(f"{API}/organizations/{org}/ai-apps", headers=auth(ai["owner"])).json()
    assert next(a for a in inv["apps"] if a["app_key"] == "zapier")["status"] == "risk_accepted"


def test_blocked_app_still_seen_after_block(client, ai):
    assert _decide(client, ai, "deepseek", ai["owner"], decision="blocked", note="Data stored in China").status_code == 201
    item = lambda: next(a for a in client.get(f"{API}/organizations/{ai['org']}/ai-apps",  # noqa: E731
                                              headers=auth(ai["owner"])).json()["apps"] if a["app_key"] == "deepseek")
    assert item()["status"] == "blocked" and item()["still_in_use"] is False
    later = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    assert _import(client, ai, text=f"Domain,User,Date\nchat.deepseek.com,liam@x.example,{later}\n").status_code == 200
    it = item()
    assert it["still_in_use"] is True and it["recommended_action"]["action"] == "confirm_removed"


def test_decisions_and_imports_are_audited(client, ai):
    events = client.get(f"{API}/organizations/{ai['org']}/audit", headers=auth(ai["owner"])).json()["events"]
    actions = [e["action"] for e in events]
    assert "ai.import" in actions and "ai.decision" in actions
    assert client.get(f"{API}/organizations/{ai['org']}/audit/verify", headers=auth(ai["owner"])).json()["valid"] is True


def test_catalog_endpoints(client, ai):
    r = client.get(f"{API}/ai-catalog", headers=auth(ai["eng"]))
    assert r.status_code == 200 and len(r.json()["apps"]) >= 40
    assert "match" not in r.json()["apps"][0]
    assert client.get(f"{API}/ai-catalog/claude", headers=auth(ai["eng"])).json()["vendor"] == "Anthropic"
    assert client.get(f"{API}/ai-catalog/claude").status_code in (401, 403)


@pg_only
def test_decision_history_is_append_only_in_postgres(client, ai):
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError
    with pytest.raises(DBAPIError):
        with db.transaction() as conn:
            conn.execute(text("UPDATE ai_app_decisions SET decision='approved'"))
    with pytest.raises(DBAPIError):
        with db.transaction() as conn:
            conn.execute(text("DELETE FROM ai_app_decisions"))


# ── MSP rollup ────────────────────────────────────────────────────────────────

def test_msp_ai_rollup(client, msp_token, other_msp_token):
    ids = []
    for name in ("Acme Dental", "Bolt Logistics", "Cedar Law"):
        r = client.post(f"{API}/msp/msp-test-001/orgs", json={"name": f"AI {name}"}, headers=auth(msp_token))
        assert r.status_code == 201, r.text
        ids.append(r.json()["org_id"])
    for org in ids[:2]:
        r = client.post(f"{API}/organizations/{org}/ai-apps/import", json={"csv_text": SAMPLE}, headers=auth(msp_token))
        assert r.status_code == 200, r.text
    r = client.get(f"{API}/msp/msp-test-001/ai-usage", headers=auth(msp_token))
    assert r.status_code == 200, r.text
    body = r.json()
    mine = [c for c in body["clients"] if c["org_id"] in ids]
    assert len(mine) == 3 and sum(c["scanned"] for c in mine) == 2
    assert body["top_apps"][0]["clients"] >= 2
    assert any(o["category"] == "meeting_assistant" for o in body["opportunities"])
    assert client.get(f"{API}/msp/msp-test-001/ai-usage", headers=auth(other_msp_token)).status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# Microsoft 365 scanner (Graph mocked)
# ══════════════════════════════════════════════════════════════════════════════

def _graph_transport():
    grants = {"value": [
        {"clientId": "sp-otter", "consentType": "Principal", "principalId": "u1", "scope": " openid Calendars.Read offline_access "},
        {"clientId": "sp-otter", "consentType": "Principal", "principalId": "u2", "scope": "openid Calendars.Read"},
        {"clientId": "sp-teams", "consentType": "AllPrincipals", "principalId": None, "scope": "User.Read"},
        {"clientId": "sp-copilot", "consentType": "AllPrincipals", "principalId": None, "scope": "User.Read"},
    ], "@odata.nextLink": "https://graph.microsoft.com/v1.0/oauth2PermissionGrants?page=2"}
    page2 = {"value": [{"clientId": "sp-docu", "consentType": "Principal", "principalId": "u1", "scope": "openid"}]}
    sps = {
        "sp-otter": {"appId": "a-otter", "displayName": "Otter.ai", "homepage": "https://otter.ai", "appOwnerOrganizationId": "t-otter"},
        "sp-teams": {"appId": "a-teams", "displayName": "Microsoft Teams", "appOwnerOrganizationId": m365.MICROSOFT_FIRST_PARTY_TENANT},
        "sp-copilot": {"appId": "a-cop", "displayName": "Microsoft 365 Copilot", "appOwnerOrganizationId": m365.MICROSOFT_FIRST_PARTY_TENANT},
        "sp-docu": {"appId": "a-docu", "displayName": "DocuSign", "replyUrls": ["https://account.docusign.com/cb"], "appOwnerOrganizationId": "t-d"},
    }
    users = {"u1": {"userPrincipalName": "maria@contoso.example", "department": "Sales"},
             "u2": {"userPrincipalName": "dev@contoso.example", "department": "Inside Sales"}}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        assert request.headers["Authorization"] == "Bearer tok"
        if "oauth2PermissionGrants" in url:
            return httpx.Response(200, json=page2 if "page=2" in url else grants)
        for sp_id, sp in sps.items():
            if f"/servicePrincipals/{sp_id}" in url:
                return httpx.Response(200, json=sp)
        for uid, u in users.items():
            if f"/users/{uid}" in url:
                return httpx.Response(200, json=u)
        return httpx.Response(404, json={})
    return httpx.MockTransport(handler)


def test_m365_collector_to_import_roundtrip():
    client = m365.GraphClient("tok", transport=_graph_transport())
    rows = m365.collect(client)
    names = [r["App"] for r in rows]
    assert "Microsoft Teams" not in names                     # first-party, not AI
    assert "Microsoft 365 Copilot" in names and "DocuSign" in names
    otter = [r for r in rows if r["App"] == "Otter.ai"]
    assert {r["User"] for r in otter} == {"maria@contoso.example", "dev@contoso.example"}
    assert otter[0]["Scopes"] == "openid Calendars.Read offline_access"
    result = importers.parse_csv(m365.to_csv(rows))
    keys = {o["app_key"]: o for o in result.observations}
    assert set(keys) == {"otter", "microsoft_copilot"}        # DocuSign dropped as non-AI
    assert keys["otter"]["users"][0]["department"] == "Sales"
    assert keys["microsoft_copilot"]["consent_types"] == ["AllPrincipals"]


def test_m365_token_errors_are_readable():
    t = httpx.MockTransport(lambda req: httpx.Response(401, json={"error_description": "AADSTS7000215: Invalid client secret"}))
    with pytest.raises(m365.GraphError) as exc:
        m365.acquire_token("tenant", "client", "bad", transport=t)
    assert "Invalid client secret" in str(exc.value)

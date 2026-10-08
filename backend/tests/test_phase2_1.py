"""
Phase 2.1 acceptance tests — RBAC is load-bearing.

  A. Role × permission matrix: every role (plus no-membership and expired)
     against a probe endpoint for each permission, asserted against
     ROLE_PERMISSIONS — so the table in permissions.py is the spec.
  B. Score cannot be faked: no route lets anyone set "pass" / "not_applicable";
     the score moves only on approval or attestation.
  C. Bootstrap without seeding: self-serve orgs, MSP provisioning, invites.
  D. Risk acceptance rules.
  E. No self-attestation.
  F. Membership expiry is enforced.
"""

from datetime import datetime, timedelta, timezone

import pytest

import backend.repositories.org_membership_repo as membership_module
from backend.auth.permissions import ALL_PERMISSIONS, ROLE_PERMISSIONS
from backend.tests.conftest import (
    API,
    add_member,
    auth,
    create_org,
    future_iso,
    invite_and_accept,
    make_token,
)

ATTEST = {
    "source_name": "Microsoft Defender",
    "source_description": "EDR on all endpoints",
    "control_ids": ["CTRL-DEV-003"],
    "confirmation_phrase": "ATTEST",
}


def _new_finding(client, org, token, severity="high", control="CTRL-ID-001"):
    r = client.post(f"{API}/organizations/{org}/findings",
                    json={"title": "gap", "description": "d", "severity": severity, "control_ids": [control]},
                    headers=auth(token))
    assert r.status_code == 201, r.text
    return r.json()["finding"]["finding_id"]


def _act(client, org, fid, token, action, **extra):
    return client.post(f"{API}/organizations/{org}/findings/{fid}/transition",
                       json={"action": action, **extra}, headers=auth(token))


def _score(client, org, token):
    r = client.get(f"{API}/organizations/{org}/score", headers=auth(token))
    assert r.status_code == 200, r.text
    return r.json()["total_score"]


# ══════════════════════════════════════════════════════════════════════════════
# A. Role × permission matrix
# ══════════════════════════════════════════════════════════════════════════════

MATRIX_ROLES = ["admin", "executive", "engineer", "msp_technician", "auditor"]


@pytest.fixture(scope="module")
def matrix(client):
    """
    One org with one helper user per role (for setup) and one *probe* user per
    role who holds ONLY that role.  Probes act; helpers prepare state.
    """
    owner = make_token("mx-owner")
    org = create_org(client, owner, "Matrix Co")                    # mx-owner: admin
    helper_exec = make_token("mx-helper-exec")
    assert invite_and_accept(client, owner, org, "executive", helper_exec).status_code == 200
    add_member(client, owner, org, "mx-helper-eng", "engineer")

    probes = {}
    for role in MATRIX_ROLES:
        uid = f"mx-probe-{role}"
        tok = make_token(uid)
        if role == "executive":
            assert invite_and_accept(client, owner, org, "executive", tok).status_code == 200
        elif role == "auditor":
            add_member(client, owner, org, uid, "auditor", expires_at=future_iso(30))
        else:
            add_member(client, owner, org, uid, role)
        probes[role] = tok
    probes["no_membership"] = make_token("mx-probe-nobody")

    return {
        "org": org,
        "owner": owner,
        "helper_exec": helper_exec,
        "helper_eng": make_token("mx-helper-eng"),
        "probes": probes,
    }


def _probe(client, m, permission, token):
    """Exercise exactly one permission and return the HTTP status."""
    org, eng, hexec = m["org"], m["helper_eng"], m["helper_exec"]

    if permission == "finding.view":
        return client.get(f"{API}/organizations/{org}/findings", headers=auth(token)).status_code

    if permission == "finding.assign":
        fid = _new_finding(client, org, eng, "medium")
        return _act(client, org, fid, token, "assign", assigned_to_user_id="mx-helper-eng").status_code

    if permission == "finding.remediate":
        return client.patch(f"{API}/organizations/{org}/statuses",
                            json={"control_id": "CTRL-ORG-001", "status": "fail"},
                            headers=auth(token)).status_code

    if permission == "finding.approve_close":
        fid = _new_finding(client, org, eng, "high")
        _act(client, org, fid, hexec, "assign", assigned_to_user_id="mx-helper-eng")
        _act(client, org, fid, eng, "start")
        _act(client, org, fid, eng, "submit")
        return _act(client, org, fid, token, "approve").status_code

    if permission == "attestation.create":
        return client.post(f"{API}/organizations/{org}/attestations", json=ATTEST,
                           headers=auth(token)).status_code

    if permission == "attestation.revoke":
        r = client.post(f"{API}/organizations/{org}/attestations", json=ATTEST, headers=auth(hexec))
        assert r.status_code == 201, r.text
        aid = r.json()["attestation"]["id"]
        return client.post(f"{API}/organizations/{org}/attestations/{aid}/revoke",
                           json={"reason": "probe"}, headers=auth(token)).status_code

    if permission == "risk.accept":
        fid = _new_finding(client, org, eng, "medium")
        return _act(client, org, fid, token, "risk_accept", expires_at=future_iso(30),
                    justification="Compensating control in place until vendor patch ships").status_code

    if permission == "org.manage":
        return client.get(f"{API}/organizations/{org}/members", headers=auth(token)).status_code

    if permission == "audit.export":
        return client.get(f"{API}/organizations/{org}/audit", headers=auth(token)).status_code

    if permission == "ai.import":
        return client.post(f"{API}/organizations/{org}/ai-apps/import",
                           json={"csv_text": "App,User\nChatGPT,probe@example.com\n"},
                           headers=auth(token)).status_code

    if permission == "ai.decide":
        r = client.post(f"{API}/organizations/{org}/ai-apps/import",
                        json={"csv_text": "App,User\nPerplexity,helper@example.com\n"}, headers=auth(eng))
        assert r.status_code == 200, r.text
        return client.post(f"{API}/organizations/{org}/ai-apps/perplexity/decision",
                           json={"decision": "under_review"}, headers=auth(token)).status_code

    if permission == "billing.manage":
        pytest.skip("No billing endpoint yet — covered by the ROLE_PERMISSIONS table only")

    raise AssertionError(f"No probe for {permission}")


_CASES = [(role, perm) for role in MATRIX_ROLES for perm in sorted(ALL_PERMISSIONS)]


@pytest.mark.parametrize("role,permission", _CASES, ids=[f"{r}:{p}" for r, p in _CASES])
def test_role_matrix(client, matrix, role, permission):
    status = _probe(client, matrix, permission, matrix["probes"][role])
    allowed = permission in ROLE_PERMISSIONS[role]
    if allowed:
        assert status in (200, 201), f"{role} should have {permission}, got {status}"
    else:
        assert status == 403, f"{role} must NOT have {permission}, got {status}"


@pytest.mark.parametrize("permission", sorted(ALL_PERMISSIONS - {"billing.manage"}))
def test_no_membership_gets_404_everywhere(client, matrix, permission):
    assert _probe(client, matrix, permission, matrix["probes"]["no_membership"]) == 404


def test_matrix_matches_spec():
    """Guard the separation-of-duties rows explicitly, not just via the table."""
    assert "attestation.create" not in ROLE_PERMISSIONS["admin"]
    assert "finding.approve_close" not in ROLE_PERMISSIONS["admin"]
    assert "finding.remediate" not in ROLE_PERMISSIONS["admin"]
    assert "risk.accept" not in ROLE_PERMISSIONS["admin"]
    assert "finding.assign" not in ROLE_PERMISSIONS["engineer"]
    assert {"finding.assign", "finding.remediate"} <= ROLE_PERMISSIONS["msp_technician"]
    assert "attestation.create" not in ROLE_PERMISSIONS["msp_technician"]
    assert ROLE_PERMISSIONS["auditor"] == {"finding.view", "audit.export"}


# ══════════════════════════════════════════════════════════════════════════════
# B. The score cannot be faked
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def scored(client):
    owner = make_token("sc-owner")
    org = create_org(client, owner, "Score Co")
    exec_tok = make_token("sc-exec")
    assert invite_and_accept(client, owner, org, "executive", exec_tok).status_code == 200
    add_member(client, owner, org, "sc-eng", "engineer")
    return {"org": org, "owner": owner, "exec": exec_tok, "eng": make_token("sc-eng")}


def test_no_membership_cannot_write_status_or_read_score(client, scored):
    nobody = make_token("sc-nobody", org_id=scored["org"])  # claiming the org in the token is not enough
    org = scored["org"]
    r = client.patch(f"{API}/organizations/{org}/statuses",
                     json={"control_id": "CTRL-ID-001", "status": "pass"}, headers=auth(nobody))
    assert r.status_code == 404
    assert client.get(f"{API}/organizations/{org}/score", headers=auth(nobody)).status_code == 404
    assert client.get(f"{API}/organizations/{org}/passport", headers=auth(nobody)).status_code == 404


@pytest.mark.parametrize("value", ["pass", "not_applicable"])
def test_nobody_can_set_score_raising_status(client, scored, value):
    org = scored["org"]
    before = _score(client, org, scored["owner"])
    for token in (scored["eng"], scored["exec"], scored["owner"]):
        r = client.patch(f"{API}/organizations/{org}/statuses",
                         json={"control_id": "CTRL-ID-001", "status": value}, headers=auth(token))
        assert r.status_code == 403, r.text
    assert _score(client, org, scored["owner"]) == before


def test_bulk_with_one_pass_writes_nothing(client, scored):
    org = scored["org"]
    r = client.put(f"{API}/organizations/{org}/statuses/bulk",
                   json={"updates": [{"control_id": "CTRL-ORG-002", "status": "fail"},
                                     {"control_id": "CTRL-ID-001", "status": "pass"}]},
                   headers=auth(scored["eng"]))
    assert r.status_code == 403
    statuses = client.get(f"{API}/organizations/{org}/statuses", headers=auth(scored["owner"])).json()["statuses"]
    assert "CTRL-ORG-002" not in statuses


def test_score_rises_only_through_approval(client, scored):
    org = scored["org"]
    fid = _new_finding(client, org, scored["eng"], "critical", "CTRL-DATA-003")
    low = _score(client, org, scored["owner"])
    _act(client, org, fid, scored["owner"], "assign", assigned_to_user_id="sc-eng")
    _act(client, org, fid, scored["eng"], "start")
    _act(client, org, fid, scored["eng"], "submit")
    assert _score(client, org, scored["owner"]) == low       # submitted ≠ passing
    assert _act(client, org, fid, scored["exec"], "approve").status_code == 200
    assert _score(client, org, scored["owner"]) > low


def test_attestation_passes_control_and_open_finding_overrides_it(client, scored):
    org = scored["org"]
    r = client.post(f"{API}/organizations/{org}/attestations",
                    json={**ATTEST, "control_ids": ["CTRL-DEV-001"]}, headers=auth(scored["exec"]))
    assert r.status_code == 201
    st = client.get(f"{API}/organizations/{org}/statuses", headers=auth(scored["owner"])).json()["statuses"]
    assert st["CTRL-DEV-001"]["status"] == "pass"
    assert st["CTRL-DEV-001"]["derived_from"] == "attestation"

    _new_finding(client, org, scored["eng"], "high", "CTRL-DEV-001")
    st = client.get(f"{API}/organizations/{org}/statuses", headers=auth(scored["owner"])).json()["statuses"]
    assert st["CTRL-DEV-001"]["status"] == "fail"


def test_msp_technician_cannot_set_pass_via_msp_route(client):
    tech = make_token("sc-tech", msp_id="msp-sc")
    r = client.post(f"{API}/msp/msp-sc/orgs", json={"name": "Client"}, headers=auth(tech))
    org = r.json()["org_id"]
    for value in ("pass", "not_applicable"):
        r = client.patch(f"{API}/msp/msp-sc/orgs/{org}/statuses/CTRL-ID-001?status={value}", headers=auth(tech))
        assert r.status_code == 403, r.text
    r = client.patch(f"{API}/msp/msp-sc/orgs/{org}/statuses/CTRL-ID-001?status=fail", headers=auth(tech))
    assert r.status_code == 200
    # One state per org: the MSP write is visible through /organizations
    st = client.get(f"{API}/organizations/{org}/statuses", headers=auth(tech)).json()["statuses"]
    assert st["CTRL-ID-001"]["status"] == "fail"


# ══════════════════════════════════════════════════════════════════════════════
# C. Bootstrap without seeding
# ══════════════════════════════════════════════════════════════════════════════

def test_self_serve_org_makes_creator_admin_only(client):
    tok = make_token("bs-founder")
    r = client.post(f"{API}/organizations", json={"name": "Founder LLC"}, headers=auth(tok))
    assert r.status_code == 201
    assert r.json()["your_roles"] == ["admin"]
    assert r.json()["org_id"].startswith("org-")


def test_owner_operator_can_hold_admin_and_executive_and_it_is_audited(client):
    tok = make_token("bs-owner-op")
    org = create_org(client, tok, "Solo Practice", also_executive=True)
    events = client.get(f"{API}/organizations/{org}/audit", headers=auth(tok)).json()["events"]
    flagged = [e for e in events if e["action"] == "membership.granted"
               and e["details"]["holds_admin_and_executive"]]
    assert flagged, "Combined admin+executive holder must be visible in the audit log"


def test_org_id_claim_cannot_be_used_to_claim_an_org(client):
    tok = make_token("bs-claimant", org_id="org-i-made-up")
    r = client.post(f"{API}/organizations", json={"name": "X"}, headers=auth(tok))
    assert r.json()["org_id"] != "org-i-made-up"
    assert client.get(f"{API}/organizations/org-i-made-up/score", headers=auth(tok)).status_code == 404


@pytest.fixture(scope="module")
def msp_world(client):
    tech = make_token("bs-tech", msp_id="msp-bs")
    r = client.post(f"{API}/msp/msp-bs/orgs", json={"name": "Client Law"}, headers=auth(tech))
    assert r.status_code == 201
    return {"tech": tech, "org": r.json()["org_id"], "your_roles": r.json()["your_roles"]}


def test_msp_provisioner_gets_admin_and_technician(msp_world):
    assert msp_world["your_roles"] == ["admin", "msp_technician"]


def test_client_exec_joins_by_invite_and_attests_msp_cannot(client, msp_world):
    org, tech = msp_world["org"], msp_world["tech"]
    ceo = make_token("bs-client-ceo")
    r = invite_and_accept(client, tech, org, "executive", ceo)
    assert r.status_code == 200, r.text
    assert r.json()["your_roles"] == ["executive"]
    assert client.post(f"{API}/organizations/{org}/attestations", json=ATTEST, headers=auth(ceo)).status_code == 201
    assert client.post(f"{API}/organizations/{org}/attestations", json=ATTEST, headers=auth(tech)).status_code == 403


@pytest.mark.parametrize("who", ["provisioner", "colleague"])
def test_msp_staff_cannot_accept_client_executive_invite(client, msp_world, who):
    org, tech = msp_world["org"], msp_world["tech"]
    accepter = tech if who == "provisioner" else make_token("bs-tech-colleague", msp_id="msp-bs")
    r = invite_and_accept(client, tech, org, "executive", accepter)
    assert r.status_code == 403, r.text


def test_invite_is_single_use_and_revocable(client, msp_world):
    org, tech = msp_world["org"], msp_world["tech"]
    r = client.post(f"{API}/organizations/{org}/invites", json={"role": "engineer"}, headers=auth(tech))
    token = r.json()["token"]
    assert client.post(f"{API}/invites/accept", json={"token": token},
                       headers=auth(make_token("bs-eng-a"))).status_code == 200
    assert client.post(f"{API}/invites/accept", json={"token": token},
                       headers=auth(make_token("bs-eng-b"))).status_code == 404

    r = client.post(f"{API}/organizations/{org}/invites", json={"role": "engineer"}, headers=auth(tech))
    inv_id, token = r.json()["invite"]["invite_id"], r.json()["token"]
    assert client.delete(f"{API}/organizations/{org}/invites/{inv_id}", headers=auth(tech)).status_code == 204
    assert client.post(f"{API}/invites/accept", json={"token": token},
                       headers=auth(make_token("bs-eng-c"))).status_code == 404


def test_invite_list_never_returns_tokens(client, msp_world):
    r = client.get(f"{API}/organizations/{msp_world['org']}/invites", headers=auth(msp_world["tech"]))
    assert r.status_code == 200
    assert all("token" not in i and "token_hash" not in i for i in r.json()["invites"])


def test_auditor_invite_requires_expiry(client, msp_world):
    r = client.post(f"{API}/organizations/{msp_world['org']}/invites", json={"role": "auditor"},
                    headers=auth(msp_world["tech"]))
    assert r.status_code == 422


def test_non_admin_cannot_create_invites(client, msp_world):
    org = msp_world["org"]
    eng = make_token("bs-eng-a")  # joined as engineer above
    r = client.post(f"{API}/organizations/{org}/invites", json={"role": "engineer"}, headers=auth(eng))
    assert r.status_code == 403


def test_deleted_msp_org_leaves_nothing_reachable(client):
    tech = make_token("bs-del-tech", msp_id="msp-del")
    org = client.post(f"{API}/msp/msp-del/orgs", json={"name": "Gone"}, headers=auth(tech)).json()["org_id"]
    assert client.delete(f"{API}/msp/msp-del/orgs/{org}", headers=auth(tech)).status_code == 204
    assert client.get(f"{API}/organizations/{org}/score", headers=auth(tech)).status_code == 404
    me = client.get(f"{API}/me", headers=auth(tech)).json()
    assert all(o["org_id"] != org for o in me["organizations"])


# ══════════════════════════════════════════════════════════════════════════════
# D. Risk acceptance
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("extra,code", [
    ({}, 422),
    ({"expires_at": None, "justification": "Compensating control in place for now"}, 422),
    ({"justification": "too short"}, 422),
], ids=["nothing", "no-expiry", "short-justification"])
def test_risk_accept_requires_expiry_and_justification(client, scored, extra, code):
    fid = _new_finding(client, scored["org"], scored["eng"], "medium", "CTRL-ORG-003")
    body = {"expires_at": future_iso(30), **extra} if "justification" in extra else extra
    r = _act(client, scored["org"], fid, scored["exec"], "risk_accept", **body)
    assert r.status_code == code, r.text


def test_critical_risk_acceptance_capped_at_90_days(client, scored):
    fid = _new_finding(client, scored["org"], scored["eng"], "critical", "CTRL-NET-004")
    r = _act(client, scored["org"], fid, scored["exec"], "risk_accept",
             expires_at=future_iso(120), justification="Waiting on hardware refresh budget approval")
    assert r.status_code == 422
    r = _act(client, scored["org"], fid, scored["exec"], "risk_accept",
             expires_at=future_iso(60), justification="Waiting on hardware refresh budget approval")
    assert r.status_code == 200, r.text


def test_accepted_risk_is_never_scored_as_passing(client, scored):
    org = scored["org"]
    fid = _new_finding(client, org, scored["eng"], "medium", "CTRL-ORG-004")
    r = _act(client, org, fid, scored["exec"], "risk_accept", expires_at=future_iso(30),
             justification="Accepted until Q1 tabletop exercise is scheduled")
    assert r.status_code == 200
    st = client.get(f"{API}/organizations/{org}/statuses", headers=auth(scored["owner"])).json()["statuses"]
    assert st["CTRL-ORG-004"]["status"] == "fail"
    assert st["CTRL-ORG-004"]["risk_accepted"] is True


# ══════════════════════════════════════════════════════════════════════════════
# E. No self-attestation
# ══════════════════════════════════════════════════════════════════════════════

def test_remediator_cannot_attest_same_control(client):
    owner = make_token("sa-owner")
    org = create_org(client, owner, "SelfAttest Co")
    dual = make_token("sa-dual")
    add_member(client, owner, org, "sa-dual", "engineer")
    assert invite_and_accept(client, owner, org, "executive", dual).status_code == 200
    other_exec = make_token("sa-exec")
    assert invite_and_accept(client, owner, org, "executive", other_exec).status_code == 200

    fid = _new_finding(client, org, dual, "high", "CTRL-DEV-003")
    _act(client, org, fid, owner, "assign", assigned_to_user_id="sa-dual")
    _act(client, org, fid, dual, "start")

    r = client.post(f"{API}/organizations/{org}/attestations", json=ATTEST, headers=auth(dual))
    assert r.status_code == 409, r.text
    r = client.post(f"{API}/organizations/{org}/attestations", json=ATTEST, headers=auth(other_exec))
    assert r.status_code == 201, r.text


# ══════════════════════════════════════════════════════════════════════════════
# F. Membership expiry is enforced
# ══════════════════════════════════════════════════════════════════════════════

def test_expired_auditor_loses_all_access(client, monkeypatch):
    owner = make_token("ex-owner")
    org = create_org(client, owner, "Expiry Co")
    aud = make_token("ex-aud")
    add_member(client, owner, org, "ex-aud", "auditor", expires_at=future_iso(2))
    assert client.get(f"{API}/organizations/{org}/findings", headers=auth(aud)).status_code == 200

    later = datetime.now(timezone.utc) + timedelta(days=3)
    monkeypatch.setattr(membership_module, "utcnow", lambda: later)

    assert client.get(f"{API}/organizations/{org}/findings", headers=auth(aud)).status_code == 404
    assert client.get(f"{API}/organizations/{org}/score", headers=auth(aud)).status_code == 404
    r = client.patch(f"{API}/organizations/{org}/statuses",
                     json={"control_id": "CTRL-ID-001", "status": "fail"}, headers=auth(aud))
    assert r.status_code == 404
    me = client.get(f"{API}/me", headers=auth(aud)).json()
    assert all(o["org_id"] != org for o in me["organizations"])


def test_past_expiry_rejected_on_grant(client):
    owner = make_token("ex-owner2")
    org = create_org(client, owner, "Expiry Co 2")
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    r = client.post(f"{API}/organizations/{org}/members",
                    json={"user_id": "ex-aud2", "role": "auditor", "expires_at": past}, headers=auth(owner))
    assert r.status_code == 422
    r = client.post(f"{API}/organizations/{org}/members",
                    json={"user_id": "ex-aud2", "role": "auditor"}, headers=auth(owner))
    assert r.status_code == 422

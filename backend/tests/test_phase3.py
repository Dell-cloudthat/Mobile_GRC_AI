"""
Phase 3 acceptance tests — persistence and tamper evidence.

Runs in both modes:
  pytest backend/tests                                   → in-memory repositories
  TEST_DATABASE_URL=postgresql://... pytest backend/tests → Postgres

Tests marked `pg_only` need a real database (append-only triggers, restart
persistence, tampering via SQL) and are skipped in in-memory mode.
"""

import pytest

from backend import db
from backend.repositories.audit_repo import audit_repo
from backend.tests.conftest import API, add_member, auth, create_org, invite_and_accept, make_token

pg_only = pytest.mark.skipif(not db.is_enabled(), reason="needs TEST_DATABASE_URL (Postgres)")

ATTEST = {
    "source_name": "Huntress",
    "source_description": "Managed EDR",
    "control_ids": ["CTRL-DEV-003"],
    "confirmation_phrase": "ATTEST",
}


@pytest.fixture(scope="module")
def org3(client):
    owner = make_token("p3-owner", name="Olive Owner", email="olive@p3.example")
    org = create_org(client, owner, "Phase3 Co", also_executive=True)
    add_member(client, owner, org, "p3-eng", "engineer")
    client.get(f"{API}/me", headers=auth(make_token("p3-eng", name="Evan Engineer")))
    return {"org": org, "owner": owner, "eng": make_token("p3-eng", name="Evan Engineer")}


# ── Audit chain ───────────────────────────────────────────────────────────────

def test_audit_chain_verifies(client, org3):
    r = client.get(f"{API}/organizations/{org3['org']}/audit/verify", headers=auth(org3["owner"]))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["valid"] is True
    assert body["checked"] >= 3  # org.created + admin + executive grants + engineer grant


def test_audit_events_are_chained(client, org3):
    events = client.get(f"{API}/organizations/{org3['org']}/audit", headers=auth(org3["owner"])).json()["events"]
    assert events[0]["prev_hash"] == "0" * 64
    for prev, cur in zip(events, events[1:]):
        assert cur["prev_hash"] == prev["row_hash"]


def test_audit_verify_requires_audit_export(client, org3):
    r = client.get(f"{API}/organizations/{org3['org']}/audit/verify", headers=auth(org3["eng"]))
    assert r.status_code == 403


@pytest.mark.skipif(db.is_enabled(), reason="in-memory tamper simulation")
def test_tampering_is_detected_in_memory(client):
    owner = make_token("p3-tamper-mem")
    org = create_org(client, owner, "Tamper Mem")
    events = audit_repo.list_by_org(org)
    audit_repo._tamper_for_tests(events[0]["event_id"], action="org.renamed_by_attacker")
    r = client.get(f"{API}/organizations/{org}/audit/verify", headers=auth(owner)).json()
    assert r["valid"] is False
    assert r["first_break_seq"] == events[0]["seq"]


@pg_only
def test_tampering_is_detected_in_postgres(client):
    """An attacker with table-owner rights disables the guard and edits a row: verify catches it."""
    from sqlalchemy import text

    owner = make_token("p3-tamper-pg")
    org = create_org(client, owner, "Tamper PG")
    events = audit_repo.list_by_org(org)
    with db.transaction() as conn:
        conn.execute(text("ALTER TABLE audit_log DISABLE TRIGGER audit_log_no_update_delete"))
        conn.execute(text("UPDATE audit_log SET details = '{\"via\": \"forged\"}' WHERE event_id = :e"),
                     {"e": events[0]["event_id"]})
        conn.execute(text("ALTER TABLE audit_log ENABLE TRIGGER audit_log_no_update_delete"))
    r = client.get(f"{API}/organizations/{org}/audit/verify", headers=auth(owner)).json()
    assert r["valid"] is False
    assert r["first_break_seq"] == events[0]["seq"]


# ── Append-only enforcement in the database ───────────────────────────────────

@pg_only
@pytest.mark.parametrize("table,where", [
    ("audit_log", "true"),
    ("attestations", "true"),
    ("finding_events", "true"),
    ("attestation_revocations", "true"),
])
def test_append_only_tables_reject_update_and_delete(client, org3, table, where):
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    # Make sure each table has at least one row.
    client.post(f"{API}/organizations/{org3['org']}/attestations", json=ATTEST, headers=auth(org3["owner"]))
    a = client.post(f"{API}/organizations/{org3['org']}/attestations", json=ATTEST, headers=auth(org3["owner"]))
    client.post(f"{API}/organizations/{org3['org']}/attestations/{a.json()['attestation']['id']}/revoke",
                json={"reason": "test"}, headers=auth(org3["owner"]))

    for stmt in (f"UPDATE {table} SET org_id = org_id WHERE {where}" if table != "attestations"
                 else f"UPDATE {table} SET source_name = 'x' WHERE {where}",
                 f"DELETE FROM {table} WHERE {where}",
                 f"TRUNCATE {table} CASCADE"):
        with pytest.raises(DBAPIError, match="append-only"):
            with db.transaction() as conn:
                conn.execute(text(stmt))


# ── Persistence ───────────────────────────────────────────────────────────────

@pg_only
def test_data_survives_restart(client, org3):
    """Drop every pooled connection and build fresh repositories: data is still there."""
    from backend.repositories.sql.findings import SqlFindingRepository
    from backend.repositories.sql.memberships import SqlOrgMembershipRepository
    from backend.repositories.sql.orgs import SqlOrgRepository

    r = client.post(f"{API}/organizations/{org3['org']}/findings",
                    json={"title": "Persist me", "description": "d", "severity": "high",
                          "control_ids": ["CTRL-ID-001"]}, headers=auth(org3["eng"]))
    fid = r.json()["finding"]["finding_id"]

    db.dispose()  # simulate a process restart: no cached connections or objects survive

    assert SqlOrgRepository().get(org3["org"]).name == "Phase3 Co"
    assert SqlOrgMembershipRepository().active_roles("p3-owner", org3["org"]) == {"admin", "executive"}
    assert SqlFindingRepository().get(fid, org3["org"]).title == "Persist me"
    r = client.get(f"{API}/organizations/{org3['org']}/findings?control_id=CTRL-ID-001", headers=auth(org3["owner"]))
    assert any(f["finding_id"] == fid for f in r.json()["findings"])


@pg_only
def test_deleted_org_keeps_its_history(client):
    tech = make_token("p3-del-tech", msp_id="msp-p3")
    org = client.post(f"{API}/msp/msp-p3/orgs", json={"name": "Retained"}, headers=auth(tech)).json()["org_id"]
    ceo = make_token("p3-del-ceo")
    assert invite_and_accept(client, tech, org, "executive", ceo).status_code == 200
    assert client.post(f"{API}/organizations/{org}/attestations", json=ATTEST, headers=auth(ceo)).status_code == 201
    assert client.delete(f"{API}/msp/msp-p3/orgs/{org}", headers=auth(tech)).status_code == 204

    assert client.get(f"{API}/organizations/{org}/score", headers=auth(ceo)).status_code == 404
    from sqlalchemy import text
    with db.transaction() as conn:
        assert conn.execute(text("SELECT count(*) FROM attestations WHERE organization_id = :o"), {"o": org}).scalar() == 1
        assert conn.execute(text("SELECT deleted_at IS NOT NULL FROM organizations WHERE org_id = :o"), {"o": org}).scalar()
    assert audit_repo.verify(org)["valid"] is True


# ── Startup guards ────────────────────────────────────────────────────────────

def test_prod_refuses_to_start_without_database(monkeypatch):
    from backend.securityos_main import validate_runtime_config
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        validate_runtime_config("prod")
    validate_runtime_config("test")  # allowed


def test_readiness_probe(client):
    r = client.get("/health/ready")
    assert r.status_code == 200
    assert r.json()["database"] == ("postgresql" if db.is_enabled() else "in-memory")


def test_dev_token_endpoint_absent_outside_dev(client):
    # The test app runs with ENV=test, so the dev sign-in route must not exist.
    r = client.post(f"{API}/dev/token", json={"user_id": "x"})
    assert r.status_code == 404


# ── Endpoints the frontend uses ───────────────────────────────────────────────

def test_me_and_members_show_names(client, org3):
    me = client.get(f"{API}/me", headers=auth(org3["owner"])).json()
    org = next(o for o in me["organizations"] if o["org_id"] == org3["org"])
    assert org["org_name"] == "Phase3 Co"
    members = client.get(f"{API}/organizations/{org3['org']}/members", headers=auth(org3["owner"])).json()["members"]
    eng = next(m for m in members if m["user_id"] == "p3-eng")
    assert eng["user"]["display_name"] == "Evan Engineer"


def test_assignees_lists_only_remediators(client, org3):
    r = client.get(f"{API}/organizations/{org3['org']}/assignees", headers=auth(org3["owner"]))
    assert r.status_code == 200
    ids = [a["user_id"] for a in r.json()["assignees"]]
    assert ids == ["p3-eng"]
    assert client.get(f"{API}/organizations/{org3['org']}/assignees", headers=auth(org3["eng"])).status_code == 403


def test_findings_filter_by_control(client, org3):
    client.post(f"{API}/organizations/{org3['org']}/findings",
                json={"title": "Backups", "description": "d", "severity": "medium",
                      "control_ids": ["CTRL-DATA-003"]}, headers=auth(org3["eng"]))
    r = client.get(f"{API}/organizations/{org3['org']}/findings?control_id=CTRL-DATA-003", headers=auth(org3["eng"]))
    assert r.status_code == 200
    assert r.json()["total"] >= 1
    assert all("CTRL-DATA-003" in f["control_ids"] for f in r.json()["findings"])


def test_engineer_can_self_start_open_finding(client, org3):
    """A solo engineer can pick up an unassigned finding ("I'll take it") — it self-assigns."""
    r = client.post(f"{API}/organizations/{org3['org']}/findings",
                    json={"title": "Self start", "description": "d", "severity": "medium",
                          "control_ids": ["CTRL-ORG-001"]}, headers=auth(org3["eng"]))
    fid = r.json()["finding"]["finding_id"]
    r = client.post(f"{API}/organizations/{org3['org']}/findings/{fid}/transition",
                    json={"action": "start"}, headers=auth(org3["eng"]))
    assert r.status_code == 200, r.text
    assert r.json()["finding"]["state"] == "in_progress"
    assert r.json()["finding"]["assigned_to_user_id"] == "p3-eng"

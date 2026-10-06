"""
Pytest fixtures for SecurityOS backend tests.

Sets ENV and AUTH_DEV_PRIVATE_KEY_PATH before any modules that read them at
import time are loaded.  Must be the first conftest evaluated.

Phase 2.1: no test seeds repositories directly.  Orgs are created through
POST /organizations or POST /msp/{id}/orgs, and people join through invites or
POST /members — the same paths production uses.  Helpers for that live here.
"""

import os
import pathlib
import time
from datetime import datetime, timedelta, timezone

# ── Configure dev auth BEFORE importing app modules ───────────────────────────

_KEY_PATH = str(pathlib.Path(__file__).parent / "dev_key.pem")

# Auto-generate a test RSA private key if it doesn't exist.
# This key is ephemeral — do NOT use in production.
if not pathlib.Path(_KEY_PATH).exists():
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import (
        Encoding, PrivateFormat, NoEncryption
    )
    _priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pathlib.Path(_KEY_PATH).write_bytes(
        _priv.private_bytes(Encoding.PEM, PrivateFormat.TraditionalOpenSSL, NoEncryption())
    )

os.environ.setdefault("ENV", "test")
os.environ.setdefault("AUTH_DEV_PRIVATE_KEY_PATH", _KEY_PATH)
os.environ.setdefault("AUTH_ISSUER", "http://localhost/test-issuer")
os.environ.setdefault("AUTH_AUDIENCE", "securityos-test")

# ── Optional: run the whole suite against Postgres ────────────────────────────
# TEST_DATABASE_URL=postgresql://user:pass@localhost:5432/securityos_test pytest backend/tests
# The schema is DROPPED and re-migrated at session start, so never point this at
# a database you care about.  Without it, tests use the in-memory repositories.
if os.environ.get("TEST_DATABASE_URL"):
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
    from sqlalchemy import create_engine, text as _text
    from backend.db import database_url as _database_url

    _admin = create_engine(_database_url())
    with _admin.begin() as _c:
        _c.execute(_text("DROP SCHEMA IF EXISTS public CASCADE"))
        _c.execute(_text("CREATE SCHEMA public"))
    _admin.dispose()
    from backend.db.migrate import upgrade as _upgrade
    _upgrade()
else:
    os.environ.pop("DATABASE_URL", None)

import pytest
from fastapi.testclient import TestClient

from backend.securityos_main import app
from backend.auth.jwt import sign_dev_token

API = "/api/v1/securityos"


# ── Token + bootstrap helpers (importable by test modules) ────────────────────

def make_token(
    user_id: str,
    *,
    msp_id: str | None = None,
    name: str | None = None,
    email: str | None = None,
    org_id: str | None = None,
    expires_in: int = 3600,
    extra: dict | None = None,
) -> str:
    claims: dict = {
        "sub": user_id,
        "email": email or f"{user_id}@example.com",
        "name": name or user_id,
    }
    if org_id is not None:
        claims["org_id"] = org_id
    if msp_id is not None:
        claims["msp_id"] = msp_id
    if extra:
        claims.update(extra)
    return sign_dev_token(claims, expires_in=expires_in)


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def future_iso(days: int = 30) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def create_org(client, owner_token: str, name: str = "Test Org", *, also_executive: bool = False) -> str:
    r = client.post(f"{API}/organizations", json={"name": name, "also_executive": also_executive},
                    headers=auth(owner_token))
    assert r.status_code == 201, r.text
    return r.json()["org_id"]


def invite_and_accept(client, admin_token: str, org_id: str, role: str, invitee_token: str,
                      membership_expires_at: str | None = None):
    body = {"role": role}
    if membership_expires_at:
        body["membership_expires_at"] = membership_expires_at
    r = client.post(f"{API}/organizations/{org_id}/invites", json=body, headers=auth(admin_token))
    assert r.status_code == 201, r.text
    token = r.json()["token"]
    return client.post(f"{API}/invites/accept", json={"token": token}, headers=auth(invitee_token))


def add_member(client, admin_token: str, org_id: str, user_id: str, role: str,
               expires_at: str | None = None):
    body = {"user_id": user_id, "role": role}
    if expires_at:
        body["expires_at"] = expires_at
    r = client.post(f"{API}/organizations/{org_id}/members", json=body, headers=auth(admin_token))
    assert r.status_code == 201, r.text
    return r


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def client():
    """A TestClient that shares state across the session (in-memory store)."""
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(scope="session")
def valid_token():
    """user-abc — owner (admin + executive) of the `test_org` fixture org."""
    return make_token("user-abc", name="Test User", email="test@example.com", org_id="org-test-001")


@pytest.fixture(scope="session")
def test_org(client, valid_token):
    """
    A self-serve org created through the API by user-abc with also_executive=True
    (owner-operated small business: admin + executive).
    """
    return create_org(client, valid_token, "Test Org", also_executive=True)


@pytest.fixture(scope="session")
def org_b_token():
    """A user in a different org."""
    return make_token("user-orgb", email="orgb@example.com", org_id="org-B-999")


@pytest.fixture(scope="session")
def msp_token():
    """A token for an MSP user managing msp-test-001."""
    return make_token("user-msp", msp_id="msp-test-001", name="MSP Admin",
                      email="msp@example.com", org_id="org-msp-internal")


@pytest.fixture(scope="session")
def other_msp_token():
    """A token for a different MSP (msp-other-999)."""
    return make_token("user-other-msp", msp_id="msp-other-999", email="other@example.com",
                      org_id="org-other-internal")


@pytest.fixture(scope="session")
def expired_token():
    """A token that is already expired."""
    return make_token("user-abc", expires_in=-1)


@pytest.fixture(scope="session")
def wrong_alg_none_token():
    """
    A token with alg=none crafted manually (not signed).
    We build the header/payload manually and join with dots.
    """
    import base64
    import json as _json

    def _b64(d: dict) -> str:
        return base64.urlsafe_b64encode(_json.dumps(d).encode()).rstrip(b"=").decode()

    header = _b64({"alg": "none", "typ": "JWT"})
    payload = _b64({
        "sub": "attacker",
        "org_id": "org-test-001",
        "exp": int(time.time()) + 3600,
        "iat": int(time.time()),
    })
    return f"{header}.{payload}."

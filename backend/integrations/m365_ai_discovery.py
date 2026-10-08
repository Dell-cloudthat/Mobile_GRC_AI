"""
Microsoft 365 AI app discovery (read-only).

Lists every third-party app people in a tenant have signed into with their
work account (delegated OAuth consents), with who consented, their department
and the permissions granted, and writes a CSV that SecurityOS imports.

v1 runs as a script so no client secrets are stored in SecurityOS:

    export M365_CLIENT_SECRET=...
    python -m backend.integrations.m365_ai_discovery \
        --tenant-id <client tenant GUID or domain> \
        --client-id <app registration client ID> \
        --out client-ai-apps.csv

Then upload the CSV on the client's AI Usage screen.

App registration (in the client's tenant, or multi-tenant with admin consent),
Microsoft Graph APPLICATION permissions, all read-only:
    DelegatedPermissionGrant.Read.All   — who consented to which app
    Application.Read.All                — app names, publishers, homepages
    User.Read.All                       — consenting users' department

Later versions run this on a schedule with the secret in Azure Key Vault.
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import sys
from typing import Dict, Iterable, List, Optional
from urllib.parse import urlparse

import httpx

GRAPH = "https://graph.microsoft.com/v1.0"
# Apps owned by Microsoft's own tenant are first-party (Teams, Outlook...);
# skipped unless the catalog knows them as AI apps (e.g. Copilot).
MICROSOFT_FIRST_PARTY_TENANT = "f8cdef31-a31e-4b4a-93e4-5f571e91255a"
CSV_FIELDS = ["App", "AppId", "Domain", "Publisher", "User", "Department", "Scopes", "ConsentType"]


class GraphError(RuntimeError):
    pass


def acquire_token(tenant_id: str, client_id: str, client_secret: str,
                  transport: Optional[httpx.BaseTransport] = None) -> str:
    with httpx.Client(transport=transport, timeout=30) as http:
        r = http.post(
            f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
            data={"grant_type": "client_credentials", "client_id": client_id, "client_secret": client_secret,
                  "scope": "https://graph.microsoft.com/.default"},
        )
    if r.status_code != 200:
        raise GraphError(f"Token request failed ({r.status_code}): {r.json().get('error_description', r.text)[:300]}")
    return r.json()["access_token"]


class GraphClient:
    def __init__(self, token: str, transport: Optional[httpx.BaseTransport] = None) -> None:
        self._http = httpx.Client(transport=transport, timeout=30,
                                  headers={"Authorization": f"Bearer {token}", "ConsistencyLevel": "eventual"})

    def get(self, url: str) -> Dict:
        r = self._http.get(url if url.startswith("http") else GRAPH + url)
        if r.status_code == 404:
            return {}
        if r.status_code >= 400:
            raise GraphError(f"Graph {r.status_code} on {url}: {r.text[:300]}")
        return r.json()

    def get_all(self, url: str) -> Iterable[Dict]:
        while url:
            page = self.get(url)
            yield from page.get("value", [])
            url = page.get("@odata.nextLink")

    def close(self) -> None:
        self._http.close()


def _domain(sp: Dict) -> str:
    for candidate in [sp.get("homepage")] + list(sp.get("replyUrls") or []):
        if candidate:
            host = urlparse(candidate).hostname or ""
            if host and host not in ("localhost",):
                return host
    return ""


def collect(client: GraphClient) -> List[Dict]:
    """One row per (app, consenting user) — or one row for tenant-wide admin consent."""
    from backend.ai_governance.matcher import match

    sps: Dict[str, Dict] = {}
    users: Dict[str, Dict] = {}
    rows: List[Dict] = []

    for grant in client.get_all("/oauth2PermissionGrants?$top=999"):
        sp_id = grant.get("clientId")
        if sp_id not in sps:
            sps[sp_id] = client.get(
                f"/servicePrincipals/{sp_id}?$select=id,appId,displayName,publisherName,homepage,replyUrls,appOwnerOrganizationId"
            )
        sp = sps[sp_id]
        if not sp:
            continue
        name, domain = sp.get("displayName", ""), _domain(sp)
        is_first_party = sp.get("appOwnerOrganizationId") == MICROSOFT_FIRST_PARTY_TENANT
        if is_first_party and not match(name=name, domain=domain, app_id=sp.get("appId")):
            continue

        consent = grant.get("consentType", "")
        user_upn, dept = "", ""
        if consent == "Principal" and grant.get("principalId"):
            pid = grant["principalId"]
            if pid not in users:
                users[pid] = client.get(f"/users/{pid}?$select=userPrincipalName,department") or {}
            user_upn = users[pid].get("userPrincipalName", "")
            dept = users[pid].get("department") or ""

        rows.append({
            "App": name, "AppId": sp.get("appId", ""), "Domain": domain,
            "Publisher": sp.get("publisherName") or "", "User": user_upn, "Department": dept,
            "Scopes": (grant.get("scope") or "").strip(), "ConsentType": consent,
        })
    return rows


def to_csv(rows: List[Dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_FIELDS)
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Export AI app consents from a Microsoft 365 tenant for SecurityOS.")
    p.add_argument("--tenant-id", required=True)
    p.add_argument("--client-id", required=True)
    p.add_argument("--out", default="ai-apps.csv")
    p.add_argument("--all-apps", action="store_true", help="Keep non-AI apps too (default: only AI-looking apps)")
    args = p.parse_args(argv)

    secret = os.environ.get("M365_CLIENT_SECRET")
    if not secret:
        print("Set M365_CLIENT_SECRET in the environment (never pass secrets as arguments).", file=sys.stderr)
        return 2
    client = GraphClient(acquire_token(args.tenant_id, args.client_id, secret))
    try:
        rows = collect(client)
    finally:
        client.close()
    if not args.all_apps:
        from backend.ai_governance.matcher import match
        rows = [r for r in rows if match(name=r["App"], domain=r["Domain"], app_id=r["AppId"])]
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        f.write(to_csv(rows))
    print(f"Wrote {len(rows)} consent rows to {args.out}. Upload it on the client's AI Usage screen.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

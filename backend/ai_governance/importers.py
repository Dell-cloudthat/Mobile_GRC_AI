"""
CSV import for AI app discovery.

Accepts the exports MSPs already have, by recognising column names rather than
one fixed format:
  - Entra ID "Enterprise applications" / consent exports (app name, app ID, user, scopes)
  - Defender for Cloud Apps "Discovered apps" (app, users, domain)
  - DNS / secure web gateway logs (domain, user)
  - SecurityOS's own scanner output (backend/integrations/m365_ai_discovery.py)
  - A hand-made sheet with just an app name column

Rows can be one per user (we count users) or one per app with a user count.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from backend.ai_governance import catalog
from backend.ai_governance.matcher import match

MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 50_000

COLUMN_ALIASES: Dict[str, List[str]] = {
    "name": ["app", "application", "appname", "applicationname", "name", "displayname", "service",
             "tool", "discoveredapp", "cloudapp", "appdisplayname", "resourcedisplayname"],
    "domain": ["domain", "url", "host", "hostname", "website", "destination", "fqdn", "homepage"],
    "app_id": ["appid", "applicationid", "clientid", "clientappid"],
    "user": ["user", "username", "userprincipalname", "upn", "email", "useremail", "mail", "identity",
             "principal", "principalname", "useridentity"],
    "department": ["department", "dept", "team", "division", "businessunit"],
    "user_count": ["users", "usercount", "numberofusers", "uniqueusers", "totalusers", "users#"],
    "scopes": ["scopes", "scope", "permissions", "grantedpermissions", "delegatedpermissions", "consentedscopes"],
    "last_seen": ["lastseen", "lastused", "date", "timestamp", "lastactivity", "lastsignin", "lastaccessed",
                  "lastsignindatetime", "createddatetime", "time"],
    "consent_type": ["consenttype"],
}


class ImportError_(ValueError):
    """Raised for files we can't use; message is safe to show to the user."""


@dataclass
class ImportResult:
    observations: List[Dict] = field(default_factory=list)
    rows: int = 0
    matched_rows: int = 0
    ignored_rows: int = 0
    columns: Dict[str, str] = field(default_factory=dict)
    ignored_samples: List[str] = field(default_factory=list)


def _norm_header(h: str) -> str:
    return re.sub(r"[^a-z0-9#]", "", (h or "").lower())


def _map_columns(headers: List[str]) -> Dict[str, str]:
    normalized = {_norm_header(h): h for h in headers}
    mapping: Dict[str, str] = {}
    for field_name, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in normalized:
                mapping[field_name] = normalized[alias]
                break
    return mapping


def _parse_int(value: Optional[str]) -> int:
    if not value:
        return 0
    digits = re.sub(r"[^\d]", "", str(value))
    return int(digits) if digits else 0


def _parse_dt(value: Optional[str]) -> Optional[str]:
    if not value or not str(value).strip():
        return None
    raw = str(value).strip()
    for fmt in (None, "%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %H:%M", "%m/%d/%Y", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y"):
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00")) if fmt is None else datetime.strptime(raw, fmt)
        except ValueError:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    return None


def _split_scopes(value: Optional[str]) -> List[str]:
    if not value:
        return []
    return [s for s in re.split(r"[\s,;|]+", value.strip()) if s]


def parse_csv(text: str, *, source: str = "csv", now: Optional[str] = None) -> ImportResult:
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise ImportError_("File is larger than 5 MB. Split it or filter it to the last 90 days.")
    text = text.lstrip("﻿")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    headers = reader.fieldnames or []
    columns = _map_columns(headers)
    if "name" not in columns and "domain" not in columns:
        raise ImportError_(
            "Couldn't find an app name or domain column. Include a column named "
            "'App' (or 'Application', 'Name') or 'Domain'. Columns found: " + ", ".join(headers[:12])
        )

    now = now or datetime.now(timezone.utc).isoformat()
    result = ImportResult(columns=columns)
    obs: Dict[str, Dict] = {}

    for row in reader:
        result.rows += 1
        if result.rows > MAX_ROWS:
            raise ImportError_(f"More than {MAX_ROWS:,} rows. Filter the export to AI apps or a shorter date range.")
        get = lambda f: (row.get(columns[f]) or "").strip() if f in columns else ""  # noqa: E731
        name, domain, app_id = get("name"), get("domain"), get("app_id")
        m = match(name=name or None, domain=domain or None, app_id=app_id or None)
        if m is None:
            result.ignored_rows += 1
            sample = name or domain
            if sample and sample not in result.ignored_samples and len(result.ignored_samples) < 5:
                result.ignored_samples.append(sample)
            continue
        result.matched_rows += 1
        o = obs.setdefault(m.app_key, {
            "app_key": m.app_key, "display_name": m.display_name, "listed": m.listed,
            "sources": [source], "users": {}, "reported_user_count": 0, "scopes": set(),
            "consent_types": set(), "domains": set(), "raw_names": set(),
            "first_seen": None, "last_seen": None, "match_confidence": m.confidence,
        })
        if name:
            o["raw_names"].add(name[:200])
        if domain:
            o["domains"].add(domain[:200].lower())
        user = get("user")
        dept = catalog.normalize_department(get("department"))
        if user:
            key = user.lower()[:320]
            existing = o["users"].get(key)
            o["users"][key] = {"user": key, "department": dept or (existing or {}).get("department")}
        o["reported_user_count"] = max(o["reported_user_count"], _parse_int(get("user_count")))
        o["scopes"].update(_split_scopes(get("scopes")))
        if get("consent_type"):
            o["consent_types"].add(get("consent_type"))
        seen = _parse_dt(get("last_seen")) or now
        o["first_seen"] = min(filter(None, [o["first_seen"], seen]))
        o["last_seen"] = max(filter(None, [o["last_seen"], seen]))

    for o in obs.values():
        users = sorted(o["users"].values(), key=lambda u: u["user"])
        result.observations.append({
            **o,
            "users": users,
            "scopes": sorted(o["scopes"]),
            "consent_types": sorted(o["consent_types"]),
            "domains": sorted(o["domains"]),
            "raw_names": sorted(o["raw_names"]),
        })
    result.observations.sort(key=lambda o: o["app_key"])
    return result

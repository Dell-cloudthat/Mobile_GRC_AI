"""Merge discovery records into one observation per (org, app)."""

from __future__ import annotations

from typing import Dict, List, Optional

MAX_USERS_PER_APP = 2000


def _union(a: List[str], b: List[str]) -> List[str]:
    return sorted(set(a or []) | set(b or []))


def merge(existing: Optional[Dict], incoming: Dict, *, updated_at: str) -> Dict:
    """Return the merged observation.  Pure function shared by both repositories."""
    if existing is None:
        users = list(incoming.get("users") or [])[:MAX_USERS_PER_APP]
        base = {
            "app_key": incoming["app_key"],
            "display_name": incoming["display_name"],
            "listed": bool(incoming.get("listed")),
            "sources": sorted(set(incoming.get("sources") or [])),
            "users": users,
            "reported_user_count": int(incoming.get("reported_user_count") or 0),
            "scopes": sorted(set(incoming.get("scopes") or [])),
            "consent_types": sorted(set(incoming.get("consent_types") or [])),
            "domains": sorted(set(incoming.get("domains") or [])),
            "raw_names": sorted(set(incoming.get("raw_names") or [])),
            "first_seen": incoming.get("first_seen") or updated_at,
            "last_seen": incoming.get("last_seen") or updated_at,
        }
    else:
        by_user = {u["user"]: dict(u) for u in existing.get("users") or []}
        for u in incoming.get("users") or []:
            prev = by_user.get(u["user"], {})
            by_user[u["user"]] = {"user": u["user"], "department": u.get("department") or prev.get("department")}
        base = {
            **existing,
            "display_name": existing["display_name"],
            "sources": _union(existing.get("sources"), incoming.get("sources")),
            "users": sorted(by_user.values(), key=lambda u: u["user"])[:MAX_USERS_PER_APP],
            "reported_user_count": max(int(existing.get("reported_user_count") or 0),
                                       int(incoming.get("reported_user_count") or 0)),
            "scopes": _union(existing.get("scopes"), incoming.get("scopes")),
            "consent_types": _union(existing.get("consent_types"), incoming.get("consent_types")),
            "domains": _union(existing.get("domains"), incoming.get("domains")),
            "raw_names": _union(existing.get("raw_names"), incoming.get("raw_names")),
            "first_seen": min(filter(None, [existing.get("first_seen"), incoming.get("first_seen")])),
            "last_seen": max(filter(None, [existing.get("last_seen"), incoming.get("last_seen")])),
        }
    base["user_count"] = max(len(base["users"]), base["reported_user_count"])
    base["updated_at"] = updated_at
    return base

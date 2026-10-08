"""AI app catalog: curated knowledge loaded once from ai_apps.json."""

from __future__ import annotations

import json
import pathlib
import re
from functools import lru_cache
from typing import Dict, List, Optional

CATALOG_PATH = pathlib.Path(__file__).with_name("ai_apps.json")


@lru_cache(maxsize=1)
def _raw() -> Dict:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def reviewed_at() -> str:
    return _raw()["reviewed_at"]


def disclaimer() -> str:
    return _raw()["disclaimer"]


def apps() -> List[Dict]:
    return _raw()["apps"]


@lru_cache(maxsize=1)
def _by_id() -> Dict[str, Dict]:
    return {a["id"]: a for a in apps()}


def get(app_id: str) -> Optional[Dict]:
    return _by_id().get(app_id)


def category(cat_id: str) -> Dict:
    return _raw()["categories"].get(cat_id) or _raw()["categories"]["general_assistant"]


def categories() -> Dict[str, Dict]:
    return _raw()["categories"]


def included_assistants() -> Dict[str, Dict]:
    return _raw()["included_assistants"]


# ── Departments ───────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _department_patterns() -> List[tuple]:
    pats = []
    for dept, keywords in _raw()["departments"].items():
        for kw in keywords:
            pats.append((re.compile(rf"(?<![a-z]){re.escape(kw)}(?![a-z])"), dept, len(kw)))
    # Longer keywords first so "customer success" beats "success"-like collisions.
    pats.sort(key=lambda p: -p[2])
    return pats


def normalize_department(raw: Optional[str]) -> Optional[str]:
    """Map a free-text department ("Inside Sales - East") to a known group, or None."""
    if not raw:
        return None
    text = str(raw).strip().lower()
    if not text:
        return None
    for pattern, dept, _ in _department_patterns():
        if pattern.search(text):
            return dept
    return "Other"


def public_app(app: Dict) -> Dict:
    """Catalog entry as returned by the API (no matching internals)."""
    cat = category(app["category"])
    return {
        "id": app["id"],
        "name": app["name"],
        "vendor": app["vendor"],
        "category": app["category"],
        "category_label": cat["label"],
        "hq_country": app.get("hq_country"),
        "website": app.get("website"),
        "summary": app["summary"],
        "common_uses": app.get("common_uses", []),
        "tiers": app["tiers"],
        "soc2": app.get("soc2"),
        "flags": app.get("flags", []),
        "notes": app.get("notes"),
    }

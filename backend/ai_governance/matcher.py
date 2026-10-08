"""
Match a discovered app (name, domain, Entra app ID) to the catalog.

Order of trust: Entra app ID → domain → exact name alias → alias contained in
the name as whole words (longest alias first, so "GitHub Copilot" is not taken
for "Copilot").  Unmatched names that look like AI tools are kept as
"unlisted" so nothing AI-shaped is silently dropped; everything else is ignored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import List, Optional, Tuple
from urllib.parse import urlparse

from backend.ai_governance import catalog

UNLISTED_PREFIX = "unlisted:"

_AI_HINT = re.compile(
    r"(?<![a-z0-9])("
    r"ai|a\.i\.|gpt|llm|genai|gen ai|copilot|chatbot|chat bot|ai assistant|ai agent|"
    r"notetaker|note taker|notetaking|transcri\w*|summari[sz]\w*|openai|anthropic|claude|gemini|"
    r"mistral|llama|deepseek|grok|perplexity|midjourney|diffusion|voice clone"
    r")(?![a-z0-9])"
)


@dataclass(frozen=True)
class Match:
    app_key: str
    listed: bool
    display_name: str
    matched_on: str        # app_id | domain | name | contains | heuristic
    confidence: str        # high | medium | low


def normalize_name(value: Optional[str]) -> str:
    text = (value or "").lower().strip()
    text = re.sub(r"[‐-―]", "-", text)
    text = re.sub(r"[^a-z0-9.;:+&\- ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def host_of(value: Optional[str]) -> str:
    raw = (value or "").strip().lower()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "http://" + raw
    try:
        host = urlparse(raw).hostname or ""
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", normalize_name(value)).strip("-")[:80] or "unknown"


@lru_cache(maxsize=1)
def _indexes() -> Tuple[dict, list, dict, list]:
    by_app_id, by_domain, by_alias = {}, [], {}
    for app in catalog.apps():
        m = app.get("match", {})
        for aid in m.get("app_ids", []):
            by_app_id[aid.lower()] = app["id"]
        for d in m.get("domains", []):
            by_domain.append((d.lower(), app["id"]))
        for alias in m.get("names", []) + [app["name"]]:
            by_alias.setdefault(normalize_name(alias), app["id"])
    by_domain.sort(key=lambda x: -len(x[0]))
    aliases = sorted(by_alias.items(), key=lambda x: -len(x[0]))
    contains = [(re.compile(rf"(?<![a-z0-9]){re.escape(a)}(?![a-z0-9])"), app_id) for a, app_id in aliases if len(a) >= 3]
    return by_app_id, by_domain, by_alias, contains


def match(name: Optional[str] = None, domain: Optional[str] = None, app_id: Optional[str] = None) -> Optional[Match]:
    by_app_id, by_domain, by_alias, contains = _indexes()

    def hit(cat_id: str, how: str, conf: str) -> Match:
        return Match(cat_id, True, catalog.get(cat_id)["name"], how, conf)

    if app_id and app_id.strip().lower() in by_app_id:
        return hit(by_app_id[app_id.strip().lower()], "app_id", "high")

    host = host_of(domain)
    if host:
        for d, cat_id in by_domain:
            if host == d or host.endswith("." + d):
                return hit(cat_id, "domain", "high")

    norm = normalize_name(name)
    if norm:
        if norm in by_alias:
            return hit(by_alias[norm], "name", "high")
        for pattern, cat_id in contains:
            if pattern.search(norm):
                return hit(cat_id, "contains", "medium")
        if _AI_HINT.search(norm) or (host and _AI_HINT.search(host.replace(".", " "))):
            display = (name or host).strip()[:200]
            return Match(UNLISTED_PREFIX + slug(display), False, display, "heuristic", "low")
    elif host and _AI_HINT.search(host.replace(".", " ")):
        return Match(UNLISTED_PREFIX + slug(host), False, host, "heuristic", "low")
    return None


def is_unlisted(app_key: str) -> bool:
    return app_key.startswith(UNLISTED_PREFIX)


def known_app_keys() -> List[str]:
    return [a["id"] for a in catalog.apps()]

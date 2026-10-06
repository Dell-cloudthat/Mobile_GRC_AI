"""Shared helpers for the Postgres repositories."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


def to_dt(value: Optional[str]) -> Optional[datetime]:
    """ISO-8601 string (domain objects) → aware datetime (database)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_iso(value: Optional[datetime]) -> Optional[str]:
    """Aware datetime (database) → ISO-8601 UTC string (domain objects)."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)

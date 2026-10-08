"""
SecurityOS database schema — Phase 3 (SQLAlchemy Core).

Append-only tables (UPDATE / DELETE / TRUNCATE blocked by triggers, see
migrations/versions/0001_baseline.py):
  finding_events, attestations, attestation_revocations, audit_log

Mutable tables hold current state; their history lives in the append-only
tables:
  organizations (soft delete via deleted_at), users, org_memberships,
  invites, findings (current state projection), manual_statuses
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Table,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

metadata = MetaData()

TS = DateTime(timezone=True)

organizations = Table(
    "organizations", metadata,
    Column("org_id", String(64), primary_key=True),
    Column("name", String(200), nullable=False),
    Column("created_by", String(255), nullable=False),
    Column("created_at", TS, nullable=False),
    Column("updated_at", TS, nullable=False),
    Column("msp_id", String(128), nullable=True, index=True),
    Column("contact_email", String(320)),
    Column("notes", Text),
    Column("profile", JSONB, nullable=False, server_default="{}"),
    Column("deleted_at", TS, nullable=True),
)

users = Table(
    "users", metadata,
    Column("user_id", String(255), primary_key=True),
    Column("email", String(320)),
    Column("display_name", String(200)),
    Column("first_seen", TS, nullable=False),
    Column("last_seen", TS, nullable=False),
)

org_memberships = Table(
    "org_memberships", metadata,
    Column("user_id", String(255), nullable=False),
    Column("org_id", String(64), ForeignKey("organizations.org_id"), nullable=False),
    Column("role", String(32), nullable=False),
    Column("granted_by", String(255), nullable=False),
    Column("granted_at", TS, nullable=False),
    Column("expires_at", TS, nullable=True),
    PrimaryKeyConstraint("user_id", "org_id", "role"),
    Index("ix_org_memberships_org", "org_id"),
)

invites = Table(
    "invites", metadata,
    Column("invite_id", String(64), primary_key=True),
    Column("org_id", String(64), ForeignKey("organizations.org_id"), nullable=False, index=True),
    Column("role", String(32), nullable=False),
    Column("token_hash", String(64), nullable=False, unique=True),
    Column("created_by", String(255), nullable=False),
    Column("created_at", TS, nullable=False),
    Column("expires_at", TS, nullable=False),
    Column("email_hint", String(320)),
    Column("membership_expires_at", TS),
    Column("accepted_by", String(255)),
    Column("accepted_at", TS),
    Column("revoked_at", TS),
)

findings = Table(
    "findings", metadata,
    Column("finding_id", String(64), primary_key=True),
    Column("org_id", String(64), ForeignKey("organizations.org_id"), nullable=False, index=True),
    Column("title", String(300), nullable=False),
    Column("description", Text, nullable=False),
    Column("severity", String(16), nullable=False),
    Column("control_ids", ARRAY(String(64)), nullable=False),
    Column("state", String(32), nullable=False),
    Column("created_by_user_id", String(255), nullable=False),
    Column("created_at", TS, nullable=False),
    Column("updated_at", TS, nullable=False),
    Column("assigned_to_user_id", String(255)),
    Column("risk_accepted_until", TS),
    Column("risk_justification", Text),
    Column("risk_accepted_by", String(255)),
    Index("ix_findings_control_ids", "control_ids", postgresql_using="gin"),
)

finding_events = Table(
    "finding_events", metadata,
    Column("seq", BigInteger, primary_key=True, autoincrement=True),
    Column("event_id", String(64), nullable=False, unique=True),
    Column("finding_id", String(64), ForeignKey("findings.finding_id"), nullable=False, index=True),
    Column("org_id", String(64), nullable=False),
    Column("action", String(32), nullable=False),
    Column("from_state", String(32), nullable=False),
    Column("to_state", String(32), nullable=False),
    Column("actor_user_id", String(255), nullable=False),
    Column("actor_name", String(200), nullable=False),
    Column("occurred_at", TS, nullable=False),
    Column("note", Text),
)

attestations = Table(
    "attestations", metadata,
    Column("id", String(64), primary_key=True),
    Column("organization_id", String(64), ForeignKey("organizations.org_id"), nullable=False, index=True),
    Column("created_by_user_id", String(255)),
    Column("created_by_name", String(200), nullable=False),
    Column("created_by_email", String(320), nullable=False),
    Column("attestation_type", String(32), nullable=False),
    Column("scope_type", String(32), nullable=False),
    Column("control_ids", ARRAY(String(64)), nullable=False),
    Column("source_provider_id", String(128)),
    Column("source_name", String(200), nullable=False),
    Column("source_description", Text, nullable=False),
    Column("statement", Text, nullable=False),
    Column("effective_at", TS),
    Column("expires_at", TS),
    Column("validity_days", Integer, nullable=False),
    Column("created_at", TS, nullable=False),
    Column("ip_address", String(64)),
    Column("user_agent", Text),
    Column("metadata", JSONB, nullable=False, server_default="{}"),
)

attestation_revocations = Table(
    "attestation_revocations", metadata,
    Column("attestation_id", String(64), ForeignKey("attestations.id"), primary_key=True),
    Column("org_id", String(64), nullable=False),
    Column("revoked_at", TS, nullable=False),
    Column("revoked_by_user_id", String(255)),
    Column("revoked_by_name", String(200), nullable=False),
    Column("reason", Text),
)

manual_statuses = Table(
    "manual_statuses", metadata,
    Column("org_id", String(64), ForeignKey("organizations.org_id"), nullable=False),
    Column("control_id", String(64), nullable=False),
    Column("status", String(32), nullable=False),
    Column("notes", Text),
    Column("evidence_source", String(32), nullable=False),
    Column("last_checked", TS, nullable=False),
    Column("set_by", String(255), nullable=False),
    PrimaryKeyConstraint("org_id", "control_id"),
)

audit_log = Table(
    "audit_log", metadata,
    Column("seq", BigInteger, primary_key=True, autoincrement=True),
    Column("event_id", String(64), nullable=False, unique=True),
    Column("chain_key", String(64), nullable=False),
    Column("org_id", String(64)),
    Column("actor_user_id", String(255), nullable=False),
    Column("action", String(64), nullable=False),
    Column("occurred_at", TS, nullable=False),
    Column("details", JSONB, nullable=False, server_default="{}"),
    Column("prev_hash", String(64), nullable=False),
    Column("row_hash", String(64), nullable=False),
    Index("ix_audit_log_chain", "chain_key", "seq"),
)

# ── Shadow AI (v1, migration 0002) ────────────────────────────────────────────

ai_app_observations = Table(
    "ai_app_observations", metadata,
    Column("org_id", String(64), ForeignKey("organizations.org_id"), nullable=False),
    Column("app_key", String(128), nullable=False),
    Column("display_name", String(200), nullable=False),
    Column("listed", Boolean, nullable=False),
    Column("sources", ARRAY(String(32)), nullable=False),
    Column("users", JSONB, nullable=False, server_default="[]"),
    Column("reported_user_count", Integer, nullable=False, server_default="0"),
    Column("scopes", ARRAY(String(128)), nullable=False),
    Column("consent_types", ARRAY(String(32)), nullable=False),
    Column("domains", ARRAY(String(200)), nullable=False),
    Column("raw_names", ARRAY(String(200)), nullable=False),
    Column("first_seen", TS, nullable=False),
    Column("last_seen", TS, nullable=False),
    Column("updated_at", TS, nullable=False),
    PrimaryKeyConstraint("org_id", "app_key"),
)

ai_app_decisions = Table(
    "ai_app_decisions", metadata,
    Column("seq", BigInteger, primary_key=True, autoincrement=True),
    Column("decision_id", String(64), nullable=False, unique=True),
    Column("org_id", String(64), ForeignKey("organizations.org_id"), nullable=False),
    Column("app_key", String(128), nullable=False),
    Column("decision", String(32), nullable=False),
    Column("note", Text),
    Column("expires_at", TS),
    Column("decided_by_user_id", String(255), nullable=False),
    Column("decided_by_name", String(200), nullable=False),
    Column("decided_at", TS, nullable=False),
    Index("ix_ai_app_decisions_org", "org_id", "seq"),
)

APPEND_ONLY_TABLES = ("finding_events", "attestations", "attestation_revocations", "audit_log",
                      "ai_app_decisions")

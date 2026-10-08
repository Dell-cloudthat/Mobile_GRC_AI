"""Shadow AI: discovered AI apps per org and an append-only decision history.

Revision ID: 0002_shadow_ai
Revises: 0001_baseline
Create Date: 2026-10-08 18:00:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_shadow_ai"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_app_observations",
        sa.Column("org_id", sa.String(64), sa.ForeignKey("organizations.org_id"), nullable=False),
        sa.Column("app_key", sa.String(128), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("listed", sa.Boolean(), nullable=False),
        sa.Column("sources", postgresql.ARRAY(sa.String(32)), nullable=False),
        sa.Column("users", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("reported_user_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("scopes", postgresql.ARRAY(sa.String(128)), nullable=False),
        sa.Column("consent_types", postgresql.ARRAY(sa.String(32)), nullable=False),
        sa.Column("domains", postgresql.ARRAY(sa.String(200)), nullable=False),
        sa.Column("raw_names", postgresql.ARRAY(sa.String(200)), nullable=False),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("org_id", "app_key"),
    )
    op.create_table(
        "ai_app_decisions",
        sa.Column("seq", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("decision_id", sa.String(64), nullable=False),
        sa.Column("org_id", sa.String(64), sa.ForeignKey("organizations.org_id"), nullable=False),
        sa.Column("app_key", sa.String(128), nullable=False),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("decided_by_user_id", sa.String(255), nullable=False),
        sa.Column("decided_by_name", sa.String(200), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("seq"),
        sa.UniqueConstraint("decision_id"),
    )
    op.create_index("ix_ai_app_decisions_org", "ai_app_decisions", ["org_id", "seq"])
    # Same guard function as 0001: decisions are history, never edited.
    op.execute(
        "CREATE TRIGGER ai_app_decisions_no_update_delete BEFORE UPDATE OR DELETE ON ai_app_decisions "
        "FOR EACH ROW EXECUTE FUNCTION securityos_forbid_mutation();"
    )
    op.execute(
        "CREATE TRIGGER ai_app_decisions_no_truncate BEFORE TRUNCATE ON ai_app_decisions "
        "FOR EACH STATEMENT EXECUTE FUNCTION securityos_forbid_mutation();"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS ai_app_decisions_no_update_delete ON ai_app_decisions;")
    op.execute("DROP TRIGGER IF EXISTS ai_app_decisions_no_truncate ON ai_app_decisions;")
    op.drop_index("ix_ai_app_decisions_org", table_name="ai_app_decisions")
    op.drop_table("ai_app_decisions")
    op.drop_table("ai_app_observations")

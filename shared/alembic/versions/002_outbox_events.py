"""Add transactional outbox table.

Revision ID: 002_outbox
Revises: 001_initial
Create Date: 2026-09-04
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "002_outbox"
down_revision = "001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Ensure platform schema exists
    op.execute("CREATE SCHEMA IF NOT EXISTS platform;")

    op.create_table(
        "outbox_events",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("topic", sa.String(255), nullable=False),
        sa.Column("event_key", sa.String(255), nullable=True),
        sa.Column("event_type", sa.String(255), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("correlation_id", sa.String(128), nullable=True),
        sa.Column("status", sa.String(32), server_default="pending", nullable=False),
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        schema="platform",
    )

    op.create_index(
        "idx_outbox_status_created",
        "outbox_events",
        ["status", "created_at"],
        schema="platform",
    )
    op.create_index(
        "idx_outbox_tenant_topic",
        "outbox_events",
        ["tenant_id", "topic"],
        schema="platform",
    )

    # Enable RLS
    op.execute("ALTER TABLE platform.outbox_events ENABLE ROW LEVEL SECURITY;")
    op.execute("""
        CREATE POLICY outbox_tenant_isolation ON platform.outbox_events
            FOR ALL
            USING (tenant_id = NULLIF(current_setting('scvri.tenant_id', true), '')::uuid);
    """)


def downgrade() -> None:
    op.drop_table("outbox_events", schema="platform")

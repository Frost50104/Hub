"""baseline: shadow_tenants, shadow_users, sync_state, rate_limits + RLS

Revision ID: 0001
Revises:
Create Date: 2026-05-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    # shadow_tenants — cross-tenant, no RLS (the auth source of truth)
    op.create_table(
        "shadow_tenants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_shadow_tenants_slug", "shadow_tenants", ["slug"], unique=True)

    # shadow_users — tenant-scoped via RLS; deleted_at required by deletion-sync
    op.create_table(
        "shadow_users",
        sa.Column("employee_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_shadow_users_email", "shadow_users", ["email"])
    op.create_index("ix_shadow_users_tenant_id", "shadow_users", ["tenant_id"])
    op.execute("ALTER TABLE shadow_users ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY shadow_users_rls ON shadow_users
        USING (
            tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
            OR current_setting('app.bypass_rls', true) = 'on'
        )
        """
    )

    # sync_state — cross-tenant cursor table for deletion-sync worker
    op.create_table(
        "sync_state",
        sa.Column("key", sa.Text, primary_key=True),
        sa.Column("cursor", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # rate_limits — DB fallback for Redis (single fixed-window row per key)
    op.create_table(
        "rate_limits",
        sa.Column("key", sa.Text, primary_key=True),
        sa.Column("count", sa.Integer, nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("rate_limits")
    op.drop_table("sync_state")
    op.execute("DROP POLICY IF EXISTS shadow_users_rls ON shadow_users")
    op.execute("ALTER TABLE shadow_users DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_shadow_users_tenant_id", table_name="shadow_users")
    op.drop_index("ix_shadow_users_email", table_name="shadow_users")
    op.drop_table("shadow_users")
    op.drop_index("ix_shadow_tenants_slug", table_name="shadow_tenants")
    op.drop_table("shadow_tenants")

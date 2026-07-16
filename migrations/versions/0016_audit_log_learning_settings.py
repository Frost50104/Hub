"""Журнал действий + настройки learn-домена (LMS Ф0, ТЗ §27)

Revision ID: 0016
Revises: 0015
Create Date: 2026-07-16

audit_log — append-only: RLS-политики только на INSERT и SELECT (без
UPDATE/DELETE) — журнал не редактируется даже приложением под RLS.
learning_settings — singleton per tenant (JSONB), обновление по-ключево.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

RLS_POLICY = (
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid "
    "OR current_setting('app.bypass_rls', true) = 'on'"
)


def upgrade() -> None:
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "actor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("shadow_users.employee_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("object_type", sa.String(32), nullable=False),
        sa.Column("object_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("object_label", sa.String(255), nullable=True),
        sa.Column("diff", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_audit_log_tenant_created", "audit_log", ["tenant_id", "created_at"])
    op.create_index(
        "ix_audit_log_tenant_object", "audit_log", ["tenant_id", "object_type", "object_id"]
    )
    op.execute("ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_log FORCE ROW LEVEL SECURITY")
    # Append-only: политики только SELECT + INSERT. UPDATE/DELETE не имеют
    # разрешающей политики → запрещены при включённом RLS.
    op.execute(f"CREATE POLICY audit_log_select ON audit_log FOR SELECT USING ({RLS_POLICY})")
    op.execute(
        f"CREATE POLICY audit_log_insert ON audit_log FOR INSERT WITH CHECK ({RLS_POLICY})"
    )

    op.create_table(
        "learning_settings",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "data", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.execute("ALTER TABLE learning_settings ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE learning_settings FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY learning_settings_rls ON learning_settings USING ({RLS_POLICY})")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS learning_settings_rls ON learning_settings")
    op.drop_table("learning_settings")
    op.execute("DROP POLICY IF EXISTS audit_log_select ON audit_log")
    op.execute("DROP POLICY IF EXISTS audit_log_insert ON audit_log")
    op.drop_table("audit_log")

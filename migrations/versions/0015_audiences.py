"""Audience-движок: правила видимости + материализованное членство (LMS Ф0, ТЗ §18)

Revision ID: 0015
Revises: 0014
Create Date: 2026-07-16

- audiences: 1:1 владение контентным объектом (audience_id NULL = всем);
- audience_rules: include/exclude-строки, внутри строки AND непустых
  uuid[]-измерений, между include — OR, exclude вычитается;
- audience_members: материализованное членство (granted_at — для дедлайнов
  ознакомления и хуков «вступил в аудиторию»); списки фильтруются одним
  EXISTS по индексу (tenant_id, audience_id, profile_id).

ENABLE + FORCE RLS на всех трёх.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

RLS_POLICY = (
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid "
    "OR current_setting('app.bypass_rls', true) = 'on'"
)

TABLES: tuple[str, ...] = ("audiences", "audience_rules", "audience_members")

_UUID_ARRAY = postgresql.ARRAY(postgresql.UUID(as_uuid=True))


def upgrade() -> None:
    op.create_table(
        "audiences",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("is_all", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("object_hint", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_audiences_tenant", "audiences", ["tenant_id"])

    op.create_table(
        "audience_rules",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "audience_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("audiences.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("mode", sa.String(8), nullable=False),
        sa.Column("profile_ids", _UUID_ARRAY, nullable=True),
        sa.Column("position_ids", _UUID_ARRAY, nullable=True),
        sa.Column("position_group_ids", _UUID_ARRAY, nullable=True),
        sa.Column("store_ids", _UUID_ARRAY, nullable=True),
        sa.Column("store_group_ids", _UUID_ARRAY, nullable=True),
        sa.Column("franchisee_ids", _UUID_ARRAY, nullable=True),
        sa.Column("franchisee_group_ids", _UUID_ARRAY, nullable=True),
        sa.Column("department_ids", _UUID_ARRAY, nullable=True),
        sa.Column("user_group_ids", _UUID_ARRAY, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("mode IN ('include', 'exclude')", name="ck_audience_rules_mode"),
    )
    op.create_index("ix_audience_rules_tenant", "audience_rules", ["tenant_id"])
    op.create_index("ix_audience_rules_audience", "audience_rules", ["audience_id"])

    op.create_table(
        "audience_members",
        sa.Column(
            "audience_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("audiences.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "profile_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("employee_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("audience_id", "profile_id", name="pk_audience_members"),
    )
    op.create_index(
        "ix_audience_members_tenant_audience_profile",
        "audience_members",
        ["tenant_id", "audience_id", "profile_id"],
    )
    op.create_index("ix_audience_members_profile", "audience_members", ["profile_id"])

    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY {table}_rls ON {table} USING ({RLS_POLICY})")


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f"DROP POLICY IF EXISTS {table}_rls ON {table}")
        op.drop_table(table)

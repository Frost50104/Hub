"""Автосценарии + маркер предупреждения о неактивности (LMS Ф5)

Revision ID: 0027
Revises: 0026
Create Date: 2026-07-19

ENABLE + FORCE RLS на новых таблицах; employee_profiles уже под RLS.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

RLS_POLICY = (
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid "
    "OR current_setting('app.bypass_rls', true) = 'on'"
)

TABLES: tuple[str, ...] = ("automation_rules", "automation_jobs")


def upgrade() -> None:
    op.create_table(
        "automation_rules",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("trigger", sa.String(32), nullable=False),
        sa.Column(
            "position_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "course_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("due_days", sa.Integer(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "applies_from",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("shadow_users.employee_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "trigger IN ('profile_activated', 'position_assigned')",
            name="ck_automation_rules_trigger",
        ),
    )
    op.create_index("ix_automation_rules_tenant", "automation_rules", ["tenant_id"])

    op.create_table(
        "automation_jobs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "rule_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("automation_rules.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "profile_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("employee_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "course_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("rule_id", "profile_id", name="uq_automation_jobs_rule_profile"),
        sa.CheckConstraint(
            "status IN ('pending', 'done', 'cancelled')", name="ck_automation_jobs_status"
        ),
    )
    op.create_index("ix_automation_jobs_tenant", "automation_jobs", ["tenant_id"])
    op.create_index("ix_automation_jobs_rule", "automation_jobs", ["rule_id"])
    op.create_index("ix_automation_jobs_profile", "automation_jobs", ["profile_id"])

    # Маркер «предупреждён о неактивности» (cron Ф5, ТЗ §23).
    op.add_column(
        "employee_profiles",
        sa.Column("inactivity_warned_at", sa.DateTime(timezone=True), nullable=True),
    )

    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY {table}_rls ON {table} USING ({RLS_POLICY})")


def downgrade() -> None:
    op.drop_column("employee_profiles", "inactivity_warned_at")
    for table in reversed(TABLES):
        op.execute(f"DROP POLICY IF EXISTS {table}_rls ON {table}")
        op.drop_table(table)

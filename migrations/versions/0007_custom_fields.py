"""custom_field_definitions + task_custom_field_values + RLS (3.6.10)

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-29

Per-project custom fields with seven primitive types
(text/number/date/select/multi_select/person/checkbox). Values are stored as
JSONB so the schema stays type-agnostic; validation by definition.type
happens in `app.services.custom_field_validator`. RLS on both tables via
tenant_id, identical to the rest of the domain (0002..0005).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


RLS_POLICY = (
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid "
    "OR current_setting('app.bypass_rls', true) = 'on'"
)


def upgrade() -> None:
    op.create_table(
        "custom_field_definitions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("type", sa.String(16), nullable=False),
        sa.Column(
            "options",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("position", sa.Numeric(20, 6), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "type IN ('text','number','date','select','multi_select','person','checkbox')",
            name="ck_custom_field_definitions_type",
        ),
        sa.UniqueConstraint("project_id", "name", name="uq_cfd_project_name"),
    )
    op.create_index(
        "ix_cfd_project", "custom_field_definitions", ["project_id", "position"]
    )
    op.create_index("ix_cfd_tenant", "custom_field_definitions", ["tenant_id"])
    op.execute(
        "ALTER TABLE custom_field_definitions ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        f"CREATE POLICY cfd_rls ON custom_field_definitions USING ({RLS_POLICY})"
    )

    op.create_table(
        "task_custom_field_values",
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "field_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "custom_field_definitions.id", ondelete="CASCADE"
            ),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("value", postgresql.JSONB, nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("task_id", "field_id", name="pk_tcfv"),
    )
    op.create_index("ix_tcfv_field", "task_custom_field_values", ["field_id"])
    op.create_index("ix_tcfv_tenant", "task_custom_field_values", ["tenant_id"])
    op.create_index(
        "ix_tcfv_value_gin",
        "task_custom_field_values",
        ["value"],
        postgresql_using="gin",
    )
    op.execute(
        "ALTER TABLE task_custom_field_values ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        f"CREATE POLICY tcfv_rls ON task_custom_field_values USING ({RLS_POLICY})"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tcfv_rls ON task_custom_field_values")
    op.execute(
        "ALTER TABLE task_custom_field_values DISABLE ROW LEVEL SECURITY"
    )
    op.drop_table("task_custom_field_values")

    op.execute("DROP POLICY IF EXISTS cfd_rls ON custom_field_definitions")
    op.execute(
        "ALTER TABLE custom_field_definitions DISABLE ROW LEVEL SECURITY"
    )
    op.drop_table("custom_field_definitions")

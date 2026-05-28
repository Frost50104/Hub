"""projects, project_members, sections + RLS

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-27
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


RLS_POLICY = (
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid "
    "OR current_setting('app.bypass_rls', true) = 'on'"
)


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("key", sa.String(32), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("shadow_users.employee_id", ondelete="RESTRICT"),
            nullable=False,
        ),
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
        sa.UniqueConstraint("tenant_id", "key", name="uq_projects_tenant_key"),
    )
    op.create_index("ix_projects_tenant_id", "projects", ["tenant_id"])
    op.execute("ALTER TABLE projects ENABLE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY projects_rls ON projects USING ({RLS_POLICY})")

    op.create_table(
        "project_members",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "employee_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("shadow_users.employee_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column(
            "added_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "added_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("shadow_users.employee_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.UniqueConstraint(
            "project_id", "employee_id", name="uq_project_members_project_employee"
        ),
        sa.CheckConstraint(
            "role IN ('owner', 'editor', 'viewer')", name="ck_project_members_role"
        ),
    )
    op.create_index("ix_project_members_tenant_id", "project_members", ["tenant_id"])
    op.create_index("ix_project_members_project_id", "project_members", ["project_id"])
    op.create_index("ix_project_members_employee_id", "project_members", ["employee_id"])
    op.execute("ALTER TABLE project_members ENABLE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY project_members_rls ON project_members USING ({RLS_POLICY})")

    op.create_table(
        "sections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_sections_tenant_id", "sections", ["tenant_id"])
    op.create_index("ix_sections_project_id", "sections", ["project_id"])
    # DEFERRABLE INITIALLY DEFERRED — allows swap-reorder in a single tx without
    # tripping the uniqueness check on intermediate states.
    op.execute(
        """
        ALTER TABLE sections
        ADD CONSTRAINT uq_sections_project_position
        UNIQUE (project_id, position) DEFERRABLE INITIALLY DEFERRED
        """
    )
    op.execute("ALTER TABLE sections ENABLE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY sections_rls ON sections USING ({RLS_POLICY})")


def downgrade() -> None:
    for table in ("sections", "project_members", "projects"):
        op.execute(f"DROP POLICY IF EXISTS {table}_rls ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.drop_table("sections")
    op.drop_table("project_members")
    op.drop_index("ix_projects_tenant_id", table_name="projects")
    op.drop_table("projects")

"""tasks + watchers + comments + labels + activity + RLS

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-27
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


RLS_POLICY = (
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid "
    "OR current_setting('app.bypass_rls', true) = 'on'"
)


def upgrade() -> None:
    # ─── tasks ──────────────────────────────────────────────────────────────
    op.create_table(
        "tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "section_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sections.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "parent_task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="todo"),
        sa.Column("priority", sa.String(16), nullable=False, server_default="medium"),
        sa.Column(
            "assignee_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("shadow_users.employee_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("shadow_users.employee_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("position", sa.Numeric(20, 6), nullable=False),
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
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('todo', 'in_progress', 'in_review', 'done')",
            name="ck_tasks_status",
        ),
        sa.CheckConstraint(
            "priority IN ('low', 'medium', 'high', 'urgent')",
            name="ck_tasks_priority",
        ),
    )
    op.create_index("ix_tasks_tenant_id", "tasks", ["tenant_id"])
    op.create_index("ix_tasks_project_id", "tasks", ["project_id"])
    op.create_index("ix_tasks_section_id", "tasks", ["section_id"])
    op.create_index("ix_tasks_parent_task_id", "tasks", ["parent_task_id"])
    op.create_index("ix_tasks_assignee_id", "tasks", ["assignee_id"])
    op.create_index(
        "ix_tasks_project_status_position",
        "tasks",
        ["project_id", "status", "position"],
    )
    op.create_index(
        "ix_tasks_due_at_active",
        "tasks",
        ["tenant_id", "due_at"],
        postgresql_where=sa.text("status != 'done' AND archived_at IS NULL"),
    )
    # Sub-tasks limited to one level — enforced in app layer (Postgres CHECK
    # cannot reference subqueries). See `_assert_parent_one_level` in
    # app/api/tasks.py.
    op.execute("ALTER TABLE tasks ENABLE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tasks_rls ON tasks USING ({RLS_POLICY})")

    # ─── task_watchers ──────────────────────────────────────────────────────
    op.create_table(
        "task_watchers",
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "employee_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("shadow_users.employee_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("added_reason", sa.String(16), nullable=False),
        sa.Column(
            "added_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("task_id", "employee_id", name="pk_task_watchers"),
        sa.CheckConstraint(
            "added_reason IN ('assignee', 'creator', 'mentioned', 'manual')",
            name="ck_task_watchers_added_reason",
        ),
    )
    op.create_index("ix_task_watchers_tenant_id", "task_watchers", ["tenant_id"])
    op.create_index("ix_task_watchers_employee_id", "task_watchers", ["employee_id"])
    op.execute("ALTER TABLE task_watchers ENABLE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY task_watchers_rls ON task_watchers USING ({RLS_POLICY})")

    # ─── task_comments ──────────────────────────────────────────────────────
    op.create_table(
        "task_comments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "author_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("shadow_users.employee_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column(
            "mentioned_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_task_comments_tenant_id", "task_comments", ["tenant_id"])
    op.create_index("ix_task_comments_task_id", "task_comments", ["task_id"])
    op.execute("ALTER TABLE task_comments ENABLE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY task_comments_rls ON task_comments USING ({RLS_POLICY})")

    # ─── task_labels ────────────────────────────────────────────────────────
    op.create_table(
        "task_labels",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("color", sa.String(16), nullable=False, server_default="#FFB200"),
        sa.UniqueConstraint("project_id", "name", name="uq_task_labels_project_name"),
    )
    op.create_index("ix_task_labels_tenant_id", "task_labels", ["tenant_id"])
    op.create_index("ix_task_labels_project_id", "task_labels", ["project_id"])
    op.execute("ALTER TABLE task_labels ENABLE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY task_labels_rls ON task_labels USING ({RLS_POLICY})")

    op.create_table(
        "task_label_assignments",
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "label_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("task_labels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("task_id", "label_id", name="pk_task_label_assignments"),
    )

    # ─── task_activity (append-only) ────────────────────────────────────────
    op.create_table(
        "task_activity",
        sa.Column(
            "id",
            sa.BigInteger,
            sa.Identity(always=True),
            primary_key=True,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "actor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("shadow_users.employee_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_task_activity_tenant_id", "task_activity", ["tenant_id"])
    op.create_index(
        "ix_task_activity_task_id_created_at", "task_activity", ["task_id", "created_at"]
    )
    op.execute("ALTER TABLE task_activity ENABLE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY task_activity_rls ON task_activity USING ({RLS_POLICY})")


def downgrade() -> None:
    for table in (
        "task_activity",
        "task_label_assignments",
        "task_labels",
        "task_comments",
        "task_watchers",
        "tasks",
    ):
        op.execute(f"DROP POLICY IF EXISTS {table}_rls ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.drop_table("task_activity")
    op.drop_table("task_label_assignments")
    op.drop_table("task_labels")
    op.drop_table("task_comments")
    op.drop_table("task_watchers")
    op.drop_table("tasks")

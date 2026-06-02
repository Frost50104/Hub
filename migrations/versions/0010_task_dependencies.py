"""task_dependencies + RLS (Phase 4.3 Timeline/Gantt)

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-02

Adjacency table for "predecessor blocks successor" relations. Used by the
Timeline view to draw arrows between bars. Cycle detection lives in the
service layer (`app/services/dependency_cycle.py`) — DFS before INSERT —
because CHECK constraints can't express recursive queries.

Self-loops are forbidden at the table level (CHECK ne).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


RLS_POLICY = (
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid "
    "OR current_setting('app.bypass_rls', true) = 'on'"
)


def upgrade() -> None:
    op.create_table(
        "task_dependencies",
        sa.Column(
            "predecessor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "successor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint(
            "predecessor_id", "successor_id", name="pk_task_dependencies"
        ),
        sa.CheckConstraint(
            "predecessor_id <> successor_id",
            name="ck_task_dependencies_no_self_loop",
        ),
    )
    # Successor look-up — "what does this task block?" / arrow rendering.
    op.create_index(
        "ix_task_dependencies_successor",
        "task_dependencies",
        ["successor_id"],
    )
    op.create_index(
        "ix_task_dependencies_tenant", "task_dependencies", ["tenant_id"]
    )
    op.execute("ALTER TABLE task_dependencies ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY task_dependencies_rls ON task_dependencies USING ({RLS_POLICY})"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS task_dependencies_rls ON task_dependencies")
    op.execute("ALTER TABLE task_dependencies DISABLE ROW LEVEL SECURITY")
    op.drop_table("task_dependencies")

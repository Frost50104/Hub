"""task_label_assignments: tenant_id + RLS (закрытие гэпа из 0003)

Таблица была создана в 0003 без tenant_id и без RLS-policy — единственная
tenant-scoped таблица вне общей колоночной политики. Write-path к ней ещё
не существовал, так что она пуста; backfill из tasks оставлен для
идемпотентности на любых окружениях.

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

RLS_POLICY = (
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid "
    "OR current_setting('app.bypass_rls', true) = 'on'"
)


def upgrade() -> None:
    op.add_column(
        "task_label_assignments",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.execute(
        "UPDATE task_label_assignments a SET tenant_id = t.tenant_id "
        "FROM tasks t WHERE t.id = a.task_id AND a.tenant_id IS NULL"
    )
    op.alter_column("task_label_assignments", "tenant_id", nullable=False)
    op.create_index(
        "ix_task_label_assignments_tenant_id", "task_label_assignments", ["tenant_id"]
    )
    op.execute("ALTER TABLE task_label_assignments ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY task_label_assignments_rls ON task_label_assignments "
        f"USING ({RLS_POLICY})"
    )


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS task_label_assignments_rls ON task_label_assignments"
    )
    op.execute("ALTER TABLE task_label_assignments DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_task_label_assignments_tenant_id", "task_label_assignments")
    op.drop_column("task_label_assignments", "tenant_id")

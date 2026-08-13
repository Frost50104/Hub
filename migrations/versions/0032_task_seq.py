"""Номера задач «KEY-42»: tasks.seq + счётчик projects.next_task_seq

Revision ID: 0032
Revises: 0031
Create Date: 2026-08-13

Backfill нумерует существующие задачи per-project по created_at (tie-break
id — детерминизм), затем seq становится NOT NULL + UNIQUE(project_id, seq).
Счётчик next_task_seq = MAX(seq)+1; server_default '1' НЕ снимать — он
страхует create-project старым кодом в окне деплоя. Выдача номера — только
атомарным UPDATE ... RETURNING (app/api/tasks.py::_allocate_task_seq),
дыры при rollback допустимы (как в Jira). RLS-политики 0002 построчные
по tenant_id — новые колонки покрыты как есть.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0032"
down_revision: str | None = "0031"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("seq", sa.Integer(), nullable=True))
    op.execute(
        """
        WITH numbered AS (
            SELECT id, ROW_NUMBER() OVER (
                PARTITION BY project_id ORDER BY created_at, id
            ) AS rn
            FROM tasks
        )
        UPDATE tasks t SET seq = n.rn FROM numbered n WHERE t.id = n.id
        """
    )
    op.alter_column("tasks", "seq", nullable=False)
    op.create_unique_constraint("uq_tasks_project_seq", "tasks", ["project_id", "seq"])

    op.add_column(
        "projects",
        sa.Column("next_task_seq", sa.Integer(), nullable=False, server_default="1"),
    )
    op.execute(
        """
        UPDATE projects p SET next_task_seq =
            COALESCE((SELECT MAX(t.seq) FROM tasks t WHERE t.project_id = p.id), 0) + 1
        """
    )


def downgrade() -> None:
    op.drop_column("projects", "next_task_seq")
    op.drop_constraint("uq_tasks_project_seq", "tasks", type_="unique")
    op.drop_column("tasks", "seq")

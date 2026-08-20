"""Этапы проекта: project_stages + tasks.stage_id (редизайн, волна 2)

Revision ID: 0040
Revises: 0039
Create Date: 2026-08-21

Доска по макету — колонки «этапов» с пользовательскими именами и произвольным
числом, каждый этап привязан к системному статусу. `tasks.status` остаётся
зеркалом `stage.system_status`.

`tasks.stage_id` — NULLable и ON DELETE SET NULL:
- окно деплоя: `deploy.sh` катит alembic ДО рестарта сервиса, и старый код
  ещё вставляет задачи без stage_id (NOT NULL — отдельной ревизией после
  релиза кода, тот же урок, что DROP COLUMN в два деплоя);
- удаление этапа никогда не теряет задачи (API требует `move_to`, SET NULL —
  страховка; доска рисует «Без этапа» только если такие задачи есть).

Backfill: каждому проекту — 4 этапа по системным статусам (имена — как
STATUS_LABEL_RU), задачам проставлен этап своего статуса. Выполняется ПОСЛЕ
создания RLS-политики под ролью миграции (BYPASSRLS).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0040"
down_revision: str | None = "0039"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

RLS_POLICY = (
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid "
    "OR current_setting('app.bypass_rls', true) = 'on'"
)

TABLES: tuple[str, ...] = ("project_stages",)

# Порядок = позиция. Имена совпадают с STATUS_LABEL_RU — контракт «Готово»
# в ответах ассистента и тестах не меняется.
DEFAULT_STAGES: tuple[tuple[str, str], ...] = (
    ("К выполнению", "todo"),
    ("В работе", "in_progress"),
    ("На проверке", "in_review"),
    ("Готово", "done"),
)


def upgrade() -> None:
    op.create_table(
        "project_stages",
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
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("system_status", sa.String(16), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "system_status IN ('todo', 'in_progress', 'in_review', 'done')",
            name="ck_project_stages_system_status",
        ),
    )
    op.create_index("ix_project_stages_tenant", "project_stages", ["tenant_id"])
    op.create_index("ix_project_stages_project", "project_stages", ["project_id"])
    op.execute(
        "ALTER TABLE project_stages ADD CONSTRAINT uq_project_stages_project_position "
        "UNIQUE (project_id, position) DEFERRABLE INITIALLY DEFERRED"
    )

    op.add_column(
        "tasks",
        sa.Column(
            "stage_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("project_stages.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    # Индекс колонки доски: (project_id, stage_id, position) — замена
    # ix_tasks_project_status_position для выборки по этапу.
    op.create_index(
        "ix_tasks_project_stage_position", "tasks", ["project_id", "stage_id", "position"]
    )

    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY {table}_rls ON {table} USING ({RLS_POLICY})")

    # ─── Backfill: 4 этапа на проект + зеркало задачам ──────────────────────
    for position, (name, system_status) in enumerate(DEFAULT_STAGES):
        op.execute(
            sa.text(
                "INSERT INTO project_stages (tenant_id, project_id, name, system_status, position) "
                "SELECT p.tenant_id, p.id, :name, :status, :position FROM projects p"
            ).bindparams(name=name, status=system_status, position=position)
        )
    op.execute(
        "UPDATE tasks t SET stage_id = s.id FROM project_stages s "
        "WHERE s.project_id = t.project_id AND s.system_status = t.status AND t.stage_id IS NULL"
    )


def downgrade() -> None:
    # Сначала колонка — она держит FK на таблицу.
    op.drop_index("ix_tasks_project_stage_position", table_name="tasks")
    op.drop_column("tasks", "stage_id")
    for table in reversed(TABLES):
        op.execute(f"DROP POLICY IF EXISTS {table}_rls ON {table}")
        op.drop_index("ix_project_stages_project", table_name=table)
        op.drop_index("ix_project_stages_tenant", table_name=table)
        op.drop_table(table)

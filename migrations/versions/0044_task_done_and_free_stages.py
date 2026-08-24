"""Свободные колонки доски + состояние задачи «выполнена / нет»

Revision ID: 0044
Revises: 0043
Create Date: 2026-08-24

До этой ревизии доска была четырёхступенчатой ПО КОНСТРУКЦИИ: у каждой колонки
был системный статус (`project_stages.system_status`), `tasks.status` был его
зеркалом, и в проекте обязан был существовать хотя бы один этап на КАЖДЫЙ из
четырёх статусов. Колонку можно было переименовать, но нельзя было завести
доску «Идея → Согласование → Печать», не подсунув каждой колонке чужой смысл.

Теперь колонка — это просто имя, а у задачи ровно одно состояние: `done`.
Колонка и выполнение — независимые оси (модель Asana): галочку можно поставить
из любой колонки, и карточка останется на месте.

Что делает ревизия:
1. `tasks.done` + бэкфилл из `status` + CHECK `done = (completed_at IS NOT NULL)`
   — связь двух полей перестаёт держаться на одном коде (нарушений в данных
   обоих окружений нет: проверено перед выкатом).
2. Индекс-близнец `ix_tasks_due_at_open` по `done`. Существующий
   `ix_tasks_due_at_active` частичный по `status <> 'done'`: как только код
   перейдёт на `done`, просрочка и обе джобы МОЛЧА вышли бы из-под индекса.
3. `tasks.stage_id NOT NULL` (задача всегда лежит в колонке) и FK без
   `ON DELETE SET NULL`: под NOT NULL обнуление было бы ошибкой 23502, а
   `NO ACTION` проверяется в конце оператора и переживает каскад удаления
   проекта.
4. `project_stages.system_status` — снимаем NOT NULL и CHECK: новый код создаёт
   колонки, не выдумывая им системный смысл. Сами колонки `tasks.status` и
   `project_stages.system_status` дропает 0045 — `DROP COLUMN` требует двух
   деплоев (окно `deploy.sh` между `alembic upgrade` и рестартом).
5. Планы ассистента в статусе `pending` отклоняются: они хранят уже
   провалидированные `args` со старым `status` и живут 30 минут, то есть план,
   созданный до выката, исполнился бы после него.

Данные не теряются: `status`/`system_status` живы до 0045, downgrade возвращает
прежнюю схему.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0044"
down_revision: str | None = "0043"
branch_labels = None
depends_on = None

_DEFAULT_STAGES: tuple[tuple[str, str], ...] = (
    ("К выполнению", "todo"),
    ("В работе", "in_progress"),
    ("На проверке", "in_review"),
    ("Готово", "done"),
)


def upgrade() -> None:
    # ─── 1. Состояние задачи ────────────────────────────────────────────────
    op.add_column(
        "tasks",
        sa.Column("done", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.execute("UPDATE tasks SET done = (status = 'done')")
    # Страховка на случай рассинхрона, накопленного до CHECK: время закрытия
    # обязано существовать ровно у выполненных.
    op.execute("UPDATE tasks SET completed_at = now() WHERE done AND completed_at IS NULL")
    op.execute("UPDATE tasks SET completed_at = NULL WHERE NOT done AND completed_at IS NOT NULL")
    op.create_check_constraint(
        "ck_tasks_done_completed_at", "tasks", "done = (completed_at IS NOT NULL)"
    )

    # ─── 2. Индекс-близнец по done ──────────────────────────────────────────
    op.execute(
        "CREATE INDEX ix_tasks_due_at_open ON tasks (tenant_id, due_at) "
        "WHERE NOT done AND archived_at IS NULL"
    )

    # ─── 3. Колонка у задачи есть всегда ────────────────────────────────────
    # Недостающие колонки проекту (у проекта до 0040 их могло не быть вовсе).
    # Позиция считается от максимума: UNIQUE(project_id, position) DEFERRABLE
    # выстрелил бы только на COMMIT, уронив всю ревизию в самом конце.
    for name, system_status in _DEFAULT_STAGES:
        op.execute(
            sa.text(
                "INSERT INTO project_stages "
                "(tenant_id, project_id, name, system_status, position) "
                "SELECT p.tenant_id, p.id, :name, :status, "
                "  COALESCE((SELECT MAX(s2.position) + 1 FROM project_stages s2 "
                "            WHERE s2.project_id = p.id), 0) "
                "FROM projects p "
                "WHERE NOT EXISTS (SELECT 1 FROM project_stages s "
                "                  WHERE s.project_id = p.id AND s.system_status = :status)"
            ).bindparams(name=name, status=system_status)
        )
    op.execute(
        "UPDATE tasks t SET stage_id = s.id FROM project_stages s "
        "WHERE s.project_id = t.project_id AND s.system_status = t.status "
        "AND t.stage_id IS NULL"
    )
    # Остаток (статус без совпавшего этапа) — в первую колонку проекта.
    op.execute(
        "UPDATE tasks t SET stage_id = ("
        "  SELECT s.id FROM project_stages s WHERE s.project_id = t.project_id "
        "  ORDER BY s.position LIMIT 1) "
        "WHERE t.stage_id IS NULL"
    )
    op.alter_column("tasks", "stage_id", existing_type=sa.dialects.postgresql.UUID(), nullable=False)
    op.drop_constraint("tasks_stage_id_fkey", "tasks", type_="foreignkey")
    op.create_foreign_key("tasks_stage_id_fkey", "tasks", "project_stages", ["stage_id"], ["id"])

    # ─── 4. Колонка доски больше не несёт системного смысла ─────────────────
    op.drop_constraint("ck_project_stages_system_status", "project_stages", type_="check")
    op.alter_column("project_stages", "system_status", existing_type=sa.String(16), nullable=True)

    # ─── 5. Планы ассистента со старым контрактом ───────────────────────────
    op.execute("UPDATE ai_plans SET status = 'rejected' WHERE status = 'pending'")


def downgrade() -> None:
    op.execute(
        "UPDATE project_stages SET system_status = 'todo' WHERE system_status IS NULL"
    )
    op.alter_column(
        "project_stages", "system_status", existing_type=sa.String(16), nullable=False
    )
    op.create_check_constraint(
        "ck_project_stages_system_status",
        "project_stages",
        "system_status IN ('todo', 'in_progress', 'in_review', 'done')",
    )
    op.drop_constraint("tasks_stage_id_fkey", "tasks", type_="foreignkey")
    op.create_foreign_key(
        "tasks_stage_id_fkey",
        "tasks",
        "project_stages",
        ["stage_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.alter_column("tasks", "stage_id", existing_type=sa.dialects.postgresql.UUID(), nullable=True)
    op.execute("DROP INDEX IF EXISTS ix_tasks_due_at_open")
    op.drop_constraint("ck_tasks_done_completed_at", "tasks", type_="check")
    op.drop_column("tasks", "done")

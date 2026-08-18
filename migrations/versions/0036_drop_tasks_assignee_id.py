"""Удаление deprecated-зеркала tasks.assignee_id (contract-шаг после 0034)

Revision ID: 0036
Revises: 0035
Create Date: 2026-08-18

Вторая половина expand/contract, начатого в 0034. Колонка была оставлена
зеркалом первого исполнителя, чтобы деплой кода и миграция не совпали:
`deploy.sh` катит `alembic upgrade` при ЖИВОМ старом процессе, а колонка
объявлена в модели — DROP COLUMN до выката кода уронил бы в UndefinedColumn
любое чтение задач.

ПОРЯДОК ОБЯЗАТЕЛЕН: код, который не знает про колонку, должен быть в проде
ДО этой ревизии. Перед накатом проверять `grep assignee_id app/models/task.py`
на сервере — должно быть пусто.

Зачем вообще убирать: зеркало требовало синхронной записи при каждом
изменении набора исполнителей и разъезжалось на параллельных запросах
(«Очистить всех» слал N DELETE, каждый писал зеркало своим устаревшим
результатом). Источник истины один — task_assignees.

ix_tasks_assignee_id осиротел ещё в 0034: фильтры по исполнителю ушли на
EXISTS по task_assignees (там свой индекс `(employee_id, task_id)`).

Прогон с нуля не ломается: 0033 и 0034 читают колонку в raw-SQL, но они
исполняются раньше — ревизия строго потомок 0035, не ветка.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0036"
down_revision: str | None = "0035"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.drop_index("ix_tasks_assignee_id", table_name="tasks")
    # FK tasks_assignee_id_fkey уходит каскадом вместе с колонкой.
    op.drop_column("tasks", "assignee_id")


def downgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("assignee_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    # Имя FK — фактическое из БД (автоимя Postgres от sa.ForeignKey в 0003),
    # чтобы downgrade → upgrade был симметричен.
    op.create_foreign_key(
        "tasks_assignee_id_fkey",
        "tasks",
        "shadow_users",
        ["assignee_id"],
        ["employee_id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_tasks_assignee_id", "tasks", ["assignee_id"])
    # Колонку обязательно ЗАПОЛНИТЬ: 0034.downgrade() дропает task_assignees и
    # полагается на живое зеркало. Alembic идёт вниз от head, поэтому эта
    # ревизия отработает раньше 0034 — данные ещё на месте.
    op.execute(
        """
        UPDATE tasks t SET assignee_id = a.employee_id
        FROM (
            SELECT DISTINCT ON (task_id) task_id, employee_id
            FROM task_assignees
            ORDER BY task_id, position, employee_id
        ) a
        WHERE a.task_id = t.id
        """
    )

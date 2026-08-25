"""0045: дроп legacy-колонок `tasks.status` и `project_stages.system_status`.

0044 перевела задачу на одну ось «выполнена / нет» (`tasks.done`), а колонку
доски — на «только имя и позиция». Две колонки старой модели остались в БД,
потому что `DROP COLUMN` требует ДВУХ деплоев: `deploy.sh` гоняет
`alembic upgrade` ДО рестарта сервиса, и живой процесс со старой моделью
перечислял бы дропнутую колонку в каждом SELECT (SQLAlchemy не делает
`SELECT *`) — `UndefinedColumn` на каждом запросе всё окно. Код без колонок
выкачен отдельным релизом (`b982f72`).

Индексы и CHECK снимаем ЯВНО и до колонки: `DROP COLUMN` унёс бы их каскадом
молча, и `downgrade` не смог бы их вернуть.

**Downgrade частично lossy.** Колонку он вернёт, ДАННЫЕ — нет: четыре статуса
схлопнуты в булев `done`, восстановить можно только `done`/`todo`, а
`in_progress`/`in_review` потеряны навсегда. `system_status` возвращается
НУЛЛЯБЕЛЬНОЙ и без бэкфилла — `UPDATE ... 'todo' WHERE NULL` + NOT NULL +
CHECK делает следующим шагом сам `downgrade` 0044. Настоящая страховка отката
— не эта функция, а pre-migration `pg_dump -Fc` из `deploy.sh`.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0045"
down_revision: str | None = "0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # `DROP COLUMN`/`DROP INDEX` берут ACCESS EXCLUSIVE. Без таймаута миграция
    # ждала бы чужой лок (idle-in-transaction, зависший `FOR UPDATE`) сколько
    # угодно, а все новые запросы к `tasks` встали бы в очередь ЗА ней — то
    # есть трекер лёг бы целиком. Лучше упасть быстро и честно.
    op.execute("SET LOCAL lock_timeout = '5s'")

    op.drop_index("ix_tasks_project_status_position", table_name="tasks")
    op.drop_index("ix_tasks_due_at_active", table_name="tasks")
    op.drop_constraint("ck_tasks_status", "tasks", type_="check")
    op.drop_column("tasks", "status")

    op.drop_column("project_stages", "system_status")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")

    # Нуллябельной и без бэкфилла: значения расставит downgrade 0044.
    op.add_column(
        "project_stages", sa.Column("system_status", sa.String(16), nullable=True)
    )

    op.add_column("tasks", sa.Column("status", sa.String(16), nullable=True))
    # Всё, что осталось от четырёх статусов, — булев `done`.
    op.execute("UPDATE tasks SET status = CASE WHEN done THEN 'done' ELSE 'todo' END")
    op.alter_column(
        "tasks",
        "status",
        existing_type=sa.String(16),
        nullable=False,
        server_default="todo",
    )
    op.create_check_constraint(
        "ck_tasks_status",
        "tasks",
        "status IN ('todo', 'in_progress', 'in_review', 'done')",
    )
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

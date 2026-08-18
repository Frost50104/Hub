"""Множественные исполнители задач: task_assignees (+ backfill)

Revision ID: 0034
Revises: 0033
Create Date: 2026-08-18

ОС тестировщика 17.08: на задачу можно назначить нескольких исполнителей.
`task_assignees` становится ЕДИНСТВЕННЫМ источником истины; колонка
`tasks.assignee_id` в этой ревизии НАМЕРЕННО остаётся как deprecated-зеркало
первого исполнителя (position=0) и удаляется отдельной ревизией 0035.

Почему не дропаем сразу: deploy.sh катит `rsync → pg_dump → pip install →
alembic upgrade → systemctl restart`, т.е. СТАРЫЙ процесс работает всё время
миграции. SQLAlchemy перечисляет колонки явно, поэтому DROP COLUMN уронил бы
в UndefinedColumn любое чтение задач (список, доска, drawer, календарь,
timeline, /me/tasks, поиск, публичная ссылка) на всё окно pip install +
миграции, а `systemctl restart` на предыдущий билд перестал бы быть рабочим
откатом. Expand/contract снимает и то, и другое.

Отличия backfill'а от 0033 (там раздавались права, здесь переносится факт):
- БЕЗ фильтра `archived_at IS NULL` — архивная задача обязана сохранить
  исполнителя;
- БЕЗ фильтра `shadow_users.deleted_at IS NULL` — FK требует лишь наличия
  строки, а `deleted_at` мягкий: назначения уволенных прячет слой отдачи,
  не БД;
- `tenant_id` из `tasks.tenant_id` (NOT NULL, source of truth), а не из
  projects — расхождение источников уже давало дыру 0011;
- `assigned_at = tasks.created_at` — нижняя граница, детерминирована при
  повторном прогоне (в отличие от now()).

Идемпотентно (ON CONFLICT DO NOTHING).

downgrade безопасен, потому что зеркало `tasks.assignee_id` живое и
синхронное: теряются только вторичные исполнители.

ENABLE + FORCE RLS (0013 — исторический список, новые таблицы ставят FORCE
сами, как 0029).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0034"
down_revision: str | None = "0033"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

RLS_POLICY = (
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid "
    "OR current_setting('app.bypass_rls', true) = 'on'"
)

TABLES: tuple[str, ...] = ("task_assignees",)


def upgrade() -> None:
    op.create_table(
        "task_assignees",
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # CASCADE, а не SET NULL как у старой колонки: employee_id — часть PK,
        # NULL невозможен (паттерн task_watchers.employee_id). Практически не
        # срабатывает: deletion-sync — no-op, shadow_users только помечаются
        # deleted_at. Админ-скрипты, чистящие shadow_users вручную, должны об
        # этом знать.
        sa.Column(
            "employee_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("shadow_users.employee_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        # Порядок отображения. БЕЗ UNIQUE(task_id, position): уникальность
        # ломала бы перестановку внутри одной транзакции промежуточными
        # коллизиями, а детерминизм даёт ORDER BY position, employee_id.
        sa.Column("position", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "assigned_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("shadow_users.employee_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("task_id", "employee_id", name="pk_task_assignees"),
    )
    op.create_index("ix_task_assignees_tenant_id", "task_assignees", ["tenant_id"])
    # Функциональная замена ix_tasks_assignee_id: index-only scan для
    # semi-join'ов /me/tasks и всех EXISTS-фильтров. Обратный порядок
    # («исполнители задачи X», батч по task_id IN (...)) закрыт PK.
    op.create_index(
        "ix_task_assignees_employee_id", "task_assignees", ["employee_id", "task_id"]
    )

    op.execute(
        """
        INSERT INTO task_assignees
            (task_id, employee_id, tenant_id, position, assigned_by, assigned_at)
        SELECT t.id, t.assignee_id, t.tenant_id, 0, NULL, t.created_at
        FROM tasks t
        WHERE t.assignee_id IS NOT NULL
        ON CONFLICT (task_id, employee_id) DO NOTHING
        """
    )

    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY {table}_rls ON {table} USING ({RLS_POLICY})")


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f"DROP POLICY IF EXISTS {table}_rls ON {table}")
        op.drop_table(table)

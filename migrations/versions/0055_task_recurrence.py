"""Повтор задач: task_recurrences + tasks.recurrence_parent_id

Revision ID: 0055
Revises: 0054
Create Date: 2026-09-14

Запрос сотрудницы: «кнопка "Повтор" на даты задачи». В WEEEK повторы стояли на
601 задаче и при переносе потерялись безвозвратно (docs/tech-debt/weeek.md).

Две сущности с РАЗНЫМ смыслом:
- строка `task_recurrences` = «эта задача повторяется ДАЛЬШЕ». Она же токен:
  порождение следующей копии начинается с `DELETE ... RETURNING`, и правило
  переезжает на копию. Отсюда идемпотентность без флагов.
- `tasks.recurrence_parent_id` = «эта задача РОДИЛАСЬ по повтору вот этой».
  Остаётся у закрытых копий навсегда — это история серии.

`ON DELETE SET NULL` у provenance-колонки, а НЕ CASCADE: соседний
`parent_task_id` каскадный, и копипаст его определения приводил бы к тому, что
удаление старой закрытой копии уносит всю живую цепочку.

Partial-UNIQUE по `recurrence_parent_id` — второй, БД-уровневый предохранитель:
одна задача физически не может породить двух потомков, даже если завтра
появится писатель, забывший про токен.

Миграция аддитивная (новая таблица + NULLABLE-колонка без дефолта) — катится до
деплоя кода без окна `UndefinedColumn`.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0055"
down_revision: str | None = "0054"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

RLS_POLICY = (
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid "
    "OR current_setting('app.bypass_rls', true) = 'on'"
)

TABLE = "task_recurrences"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table(
        TABLE,
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("freq", sa.String(8), nullable=False),
        # `step`, а не `interval`: INTERVAL — тип и зарезервированное слово
        # Postgres, ручной SQL пришлось бы писать в кавычках.
        sa.Column("step", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("anchor", sa.Date(), nullable=False),
        sa.Column("occurrence", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("shadow_users.employee_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.CheckConstraint(
            "freq IN ('day', 'weekday', 'week', 'month')", name="ck_task_recurrences_freq"
        ),
        sa.CheckConstraint("freq <> 'weekday' OR step = 1", name="ck_task_recurrences_weekday_step"),
        sa.CheckConstraint("step BETWEEN 1 AND 365", name="ck_task_recurrences_step"),
        sa.CheckConstraint("occurrence >= 0", name="ck_task_recurrences_occurrence"),
    )
    op.create_index(f"ix_{TABLE}_tenant", TABLE, ["tenant_id"])

    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY {TABLE}_rls ON {TABLE} USING ({RLS_POLICY})")

    op.add_column(
        "tasks",
        sa.Column("recurrence_parent_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_tasks_recurrence_parent",
        "tasks",
        "tasks",
        ["recurrence_parent_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # Задача порождает потомка не более одного раза за всю жизнь.
    op.execute(
        "CREATE UNIQUE INDEX uq_tasks_recurrence_parent ON tasks (recurrence_parent_id) "
        "WHERE recurrence_parent_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("DROP INDEX IF EXISTS uq_tasks_recurrence_parent")
    op.drop_constraint("fk_tasks_recurrence_parent", "tasks", type_="foreignkey")
    op.drop_column("tasks", "recurrence_parent_id")
    op.execute(f"DROP POLICY IF EXISTS {TABLE}_rls ON {TABLE}")
    op.drop_index(f"ix_{TABLE}_tenant", table_name=TABLE)
    op.drop_table(TABLE)

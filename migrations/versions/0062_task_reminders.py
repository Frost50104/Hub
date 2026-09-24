"""0062: личные напоминания по задачам — `task_reminders`.

ОС пользователя (24.09): «кнопку напомнить ко времени». Решения владельца:
напоминание — только себе; относительное напоминание двигается вместе со
сроком; просрочка — по-прежнему по дням.

Строка — либо РАЗОВОЕ напоминание (`anchor = 'at'`, удаляется после
срабатывания), либо ПРАВИЛО относительно срока/старта (`due`, `due_day`,
`start`, `start_day` + `offset_minutes`), которое живёт дальше:
- `fire_at` — следующий момент срабатывания; NULL = сработало или «спит»
  (срока нет, время срока прошло, задача выполнена);
- `fired_anchor_at` — для какого момента якоря правило уже сработало: перенесли
  срок → правило взводится снова; повтор переносит правило на копию.
Удалять правило при срабатывании нельзя: «за 1 ч до срока» на ежедневной задаче
пропадало бы после первого же дня.

Частичный индекс по `fire_at` — единственное, что сканирует воркер (раз в
20 с). Два частичных UNIQUE гасят двойной клик: правило уникально по якорю и
сдвигу, разовое — по минуте.

RLS — как у всех доменных таблиц (ENABLE + FORCE). Воркер читает под bypass.

Revision ID: 0062
Revises: 0061
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0062"
down_revision: str | None = "0061"
branch_labels = None
depends_on = None

RLS_POLICY = (
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid "
    "OR current_setting('app.bypass_rls', true) = 'on'"
)

TABLE = "task_reminders"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table(
        TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
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
        sa.Column("anchor", sa.String(10), nullable=False),
        sa.Column(
            "offset_minutes", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("fire_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fired_anchor_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("via_admin", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.CheckConstraint(
            "anchor IN ('at', 'due', 'due_day', 'start', 'start_day')",
            name="ck_task_reminders_anchor",
        ),
        sa.CheckConstraint(
            "offset_minutes BETWEEN 0 AND 10080", name="ck_task_reminders_offset"
        ),
        sa.CheckConstraint(
            "anchor <> 'at' OR (offset_minutes = 0 AND fire_at IS NOT NULL)",
            name="ck_task_reminders_at",
        ),
    )
    op.create_index(f"ix_{TABLE}_tenant", TABLE, ["tenant_id"])
    op.create_index(f"ix_{TABLE}_task_employee", TABLE, ["task_id", "employee_id"])
    op.execute(
        f"CREATE INDEX ix_{TABLE}_fire_at ON {TABLE} (fire_at) WHERE fire_at IS NOT NULL"
    )
    op.execute(
        f"CREATE UNIQUE INDEX uq_{TABLE}_rule ON {TABLE} "
        "(task_id, employee_id, anchor, offset_minutes) WHERE anchor <> 'at'"
    )
    op.execute(
        f"CREATE UNIQUE INDEX uq_{TABLE}_at ON {TABLE} "
        "(task_id, employee_id, fire_at) WHERE anchor = 'at'"
    )

    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY {TABLE}_rls ON {TABLE} USING ({RLS_POLICY})")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(f"DROP POLICY IF EXISTS {TABLE}_rls ON {TABLE}")
    op.drop_table(TABLE)

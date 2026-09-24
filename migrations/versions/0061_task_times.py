"""0061: время у старта и срока задачи — флаги `start_has_time` / `due_has_time`.

ОС пользователя (24.09): «возможность выбрать время старта/дедлайна задачи».

До сих пор срок — КАЛЕНДАРНЫЙ ДЕНЬ display tz: мгновение `due_at` пишется
полднем МСК, а окна и просрочка считаются по границам дня (`taskdates.py`).
Время нельзя вывести из самого мгновения («не полдень — значит время задано»):
неполуденные сроки уже есть без умысла человека — перетаскивание в календаре
сохраняет час источника, CSV пишет ISO-время как прислали. Поэтому признак
явный: флаг `false` = день (как было у всех строк), `true` = точный момент.

Просрочка по-прежнему по дням (решение владельца 24.09): время — информация и
точка отсчёта для напоминаний, `overdue_clause` и окна не меняются.

Связь «флаг без даты не бывает» сторожит БД (прецедент —
`ck_tasks_done_completed_at`). Цена — ранбук отката кода: старый
`update_task` обнуляет `due_at`, не зная про флаг, и упёрся бы в CHECK, поэтому
ПЕРЕД откатом кода ограничения снимаются руками (docs/DEPLOY.md).

Колонки с константным дефолтом на PG16 — только метаданные; проверка CHECK
сканирует таблицу (≈17 тыс. строк, все `false`). Триггер 0060
`trg_tasks_template_guard` на эти колонки не подписан.

Revision ID: 0061
Revises: 0060
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0061"
down_revision: str | None = "0060"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    for col in ("start_has_time", "due_has_time"):
        op.add_column(
            "tasks",
            sa.Column(col, sa.Boolean(), nullable=False, server_default=sa.text("false")),
        )
    op.create_check_constraint(
        "ck_tasks_start_has_time", "tasks", "NOT start_has_time OR start_at IS NOT NULL"
    )
    op.create_check_constraint(
        "ck_tasks_due_has_time", "tasks", "NOT due_has_time OR due_at IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("ALTER TABLE tasks DROP CONSTRAINT IF EXISTS ck_tasks_due_has_time")
    op.execute("ALTER TABLE tasks DROP CONSTRAINT IF EXISTS ck_tasks_start_has_time")
    op.drop_column("tasks", "due_has_time")
    op.drop_column("tasks", "start_has_time")

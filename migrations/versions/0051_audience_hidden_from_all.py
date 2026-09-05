"""Аудитория «никому»: audiences.is_none — скрыть контент ото всех разом

Revision ID: 0051
Revises: 0050
Create Date: 2026-09-01

ОС владельца: запущенную аттестацию нужно временно спрятать от всех, а пикер
аудитории умеет только «всем» (audience_id NULL) и «по правилам» — оставалось
исключать 261 сотрудника по одному. Состояние «никому» в движке невыразимо:
`is_all=false` без include-строк означает «все активные» (это семантика
exclude-only аудиторий), а пустая include-строка запрещена fail-closed.

Заводим третье ЯВНОЕ состояние — флаг `is_none`, симметричный `is_all`.
Отвергнутые альтернативы: переопределить «без правил вообще» как «никому» —
молча перевернуло бы видимость zero-rule аудиторий, если такие лежат в проде;
exclude-строка «все контуры» — хак, ломающийся при появлении нового org_role.

`is_none` — оверлей: строки правил сохраняются (снятие флага возвращает
прежнюю аудиторию без перенастройки), а членство `audience_members` пересчёт
вычищает в ноль — поэтому все потребители видимости (visible_filter, обходные
пути «audience_id IS NULL ⇒ всем») гаснут без единой правки.

Additive ADD COLUMN с server_default — «правило двух деплоев» не применяется
(см. 0049): старый код колонку не читает, окно до рестарта безопасно. RLS
row-based (0015) — новая колонка покрыта автоматически.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0051"
down_revision = "0050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column(
        "audiences",
        sa.Column("is_none", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_column("audiences", "is_none")

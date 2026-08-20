"""Снять сопоставление точек Hub с iiko

Revision ID: 0039
Revises: 0038
Create Date: 2026-08-20

Решение владельца: сущности точек в Hub и в отчётах ассистента НЕ связываются.
Отчёт показывает названия так, как их ведёт iiko, и человек узнаёт точку по
имени. Причина отказаться от моста: сопоставление по имени — это перевод,
который однажды ошибётся и покажет управляющему чужую выручку, а заметить
такую ошибку почти невозможно.

Прямое следствие, принятое сознательно: сузить отчёт до «своих» точек нечем,
поэтому владелец франчайзи видит и чужие. Доступ решается ролью, а не
скоупом (`app/api/reports.py::_require_report_access`).

Колонка прожила один день (0038 → 0039) и не использовалась ничем, кроме
удалённого job'а сопоставления.

**ВТОРОЙ РЕЛИЗ.** `deploy.sh` катит rsync → pg_dump → pip install → alembic →
restart, то есть СТАРЫЙ процесс работает всё время миграции. SQLAlchemy
перечисляет колонки явно, поэтому DROP COLUMN уронит в UndefinedColumn любое
чтение магазинов (оргструктура, аудитории, скоуп) на всё окно. Порядок:
сначала деплой кода БЕЗ колонки (уже сделан), потом эта ревизия.

downgrade возвращает пустую колонку — данных в ней не было.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0039"
down_revision: str | None = "0038"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.drop_index("ix_stores_iiko_department", table_name="stores")
    op.drop_column("stores", "iiko_department")


def downgrade() -> None:
    op.add_column(
        "stores", sa.Column("iiko_department", sa.String(255), nullable=True)
    )
    op.create_index("ix_stores_iiko_department", "stores", ["iiko_department"])

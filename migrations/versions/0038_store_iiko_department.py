"""Сопоставление точки Hub с «Торговым предприятием» iiko

Revision ID: 0038
Revises: 0037
Create Date: 2026-08-20

Волна 2 ассистента (отчёты iiko). В iiko точка адресуется СТРОКОЙ-именем
(поле OLAP `Department`, например «Чапаева 17, к. 2»), в Hub — UUID в
`stores`. Без явного сопоставления:

- «выручка по точкам» показала бы иконные имена iiko вместо названий Hub;
- скоуп ТУ/франчайзи выразить нечем — фильтр OLAP принимает имена, а мы
  знаем только UUID своих магазинов, поэтому управляющий увидел бы всю сеть;
- «создать задачу по отчёту» не смогло бы привязать точку.

Nullable: у части точек соответствия может не быть (новые, закрытые), и это
не повод блокировать отчёт по остальным. UNIQUE не ставим: одно «Торговое
предприятие» iiko может обслуживать две записи Hub при переезде точки.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0038"
down_revision: str | None = "0037"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.add_column(
        "stores", sa.Column("iiko_department", sa.String(255), nullable=True)
    )
    op.create_index("ix_stores_iiko_department", "stores", ["iiko_department"])


def downgrade() -> None:
    op.drop_index("ix_stores_iiko_department", table_name="stores")
    op.drop_column("stores", "iiko_department")

"""0059: последнее применённое значение реестра у карточки магазина.

`registry_name/code/address` — что Hub в последний раз взял из объекта
реестра auth. Правило зеркала (`registry_apply`): поле карточки следует за
реестром, ПОКА оно равно последнему применённому значению (или пусто) — то
есть пока его не правили руками в Hub. У 59 бэкфилленных карточек до первого
прогона NULL: их короткие имена не переименовываются в адресные строки
реестра, а пустые адреса заполняются.

Revision ID: 0059
Revises: 0058
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0059"
down_revision: str | None = "0058"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column("stores", sa.Column("registry_name", sa.String(255), nullable=True))
    op.add_column("stores", sa.Column("registry_code", sa.String(32), nullable=True))
    op.add_column("stores", sa.Column("registry_address", sa.Text(), nullable=True))


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_column("stores", "registry_address")
    op.drop_column("stores", "registry_code")
    op.drop_column("stores", "registry_name")

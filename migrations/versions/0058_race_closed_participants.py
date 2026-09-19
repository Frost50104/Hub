"""0058: причина исключения участника гонки `closed` (точка закрыта).

Реестр auth — источник истины про точки (решение владельца 19.09): архив
объекта в реестре архивирует карточку магазина в Hub, а часовая джоба гонки
выводит такую точку из состава с `exclude_reason='closed'`. Только CHECK —
схема таблицы не меняется.

Revision ID: 0058
Revises: 0057
"""

from __future__ import annotations

from alembic import op

revision: str = "0058"
down_revision: str | None = "0057"
branch_labels = None
depends_on = None

_TABLE = "race_participants"
_NAME = "ck_race_participants_exclude_reason"
_NEW = "exclude_reason IS NULL OR exclude_reason IN ('duplicate','manual','closed')"
_OLD = "exclude_reason IS NULL OR exclude_reason IN ('duplicate','manual')"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_constraint(_NAME, _TABLE, type_="check")
    op.create_check_constraint(_NAME, _TABLE, _NEW)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    # Строки с новой причиной не должны уронить старый CHECK: считаем их
    # исключёнными вручную — состав и зачёт от этого не меняются.
    op.execute(f"UPDATE {_TABLE} SET exclude_reason = 'manual' WHERE exclude_reason = 'closed'")
    op.drop_constraint(_NAME, _TABLE, type_="check")
    op.create_check_constraint(_NAME, _TABLE, _OLD)

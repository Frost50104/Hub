"""0065: приостановка точки — `shadow_sites.suspended_at` и причина `suspended`

Revision ID: 0065
Revises: 0064
Create Date: 2026-10-20

Решение владельца 19.10 (хендофф auth `docs/handoffs/HUB_TASK_site_suspend.md`,
контракт — `client-libs/INTEGRATION.md` 16c): точка может закрыться ВРЕМЕННО —
ремонт, сезон, пауза. У объекта реестра появилась вторая ось состояния рядом с
`archived_at`: `suspended_at` — дата решения в реестре, обратимо, без рассылок.
Оси взаимоисключающие: архив обнуляет приостановку.

- `shadow_sites.suspended_at` — зеркало поля снимка, replace-синк его просто
  везёт. Магазин по нему НЕ архивируется (архив — только по `archived_at`);
- `race_participants.exclude_reason` получает `suspended`: участник выходит из
  состава на время приостановки и возвращается сам (`closed` — навсегда).

Аддитивно, правило двух деплоев не применяется: старый код колонку не читает,
а новую причину не пишет.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0065"
down_revision = "0064"
branch_labels = None
depends_on = None

_TABLE = "race_participants"
_NAME = "ck_race_participants_exclude_reason"
_NEW = "exclude_reason IS NULL OR exclude_reason IN ('duplicate','manual','closed','suspended')"
_OLD = "exclude_reason IS NULL OR exclude_reason IN ('duplicate','manual','closed')"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column(
        "shadow_sites",
        sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.drop_constraint(_NAME, _TABLE, type_="check")
    op.create_check_constraint(_NAME, _TABLE, _NEW)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    # FORCE RLS: без флага UPDATE молча обновил бы 0 строк, и старый CHECK
    # упал бы на первой же приостановленной строке.
    op.execute("SET LOCAL app.bypass_rls = 'on'")
    # Старый код приостановленного сам не вернёт: считаем его исключённым
    # вручную — `closed` соврал бы «закрыта навсегда».
    op.execute(f"UPDATE {_TABLE} SET exclude_reason = 'manual' WHERE exclude_reason = 'suspended'")
    op.drop_constraint(_NAME, _TABLE, type_="check")
    op.create_check_constraint(_NAME, _TABLE, _OLD)
    op.drop_column("shadow_sites", "suspended_at")

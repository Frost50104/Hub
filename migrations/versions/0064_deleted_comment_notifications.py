"""Уведомления удалённых комментариев — только данные

Revision ID: 0064
Revises: 0063
Create Date: 2026-09-28

До этой ревизии удаление комментария (`DELETE /comments/{id}`) ставило только
`deleted_at`, а уведомления о нём («Новый комментарий», «упомянул вас») с
цитатой удалённого текста оставались во «Входящих» у всех получателей и вели в
обсуждение, где комментария уже нет (ОС 08.09, RH-23). С этой ревизии ручка
снимает их сама (`notify.py::comment_notifications_where`); миграция убирает
то, что успело накопиться.

У старых строк нет `payload.comment_id`, поэтому пара ищется так же, как в
запасной ветке ручки: та же задача (`payload.task_id`) и тот же `created_at`.
Уведомления пишутся той же транзакцией, что и комментарий, а `now()` в
Postgres — время начала транзакции, так что метки совпадают до микросекунды.
На проде 28.09 у всех 255 уведомлений о комментариях нашлась ровно одна пара.

Ожидаемо на проде: 2 строки (#1257, #1258 — комментарий PERSONAL-4 от 08.09).

`downgrade` ничего не делает: удалённые строки не восстанавливаются, а
вернуть их незачем — они вели в пустоту.
"""

from __future__ import annotations

import logging

import sqlalchemy as sa
from alembic import op

revision = "0064"
down_revision = "0063"
branch_labels = None
depends_on = None

log = logging.getLogger("alembic.runtime.migration")

# SQL — константой, чтобы интеграционный тест гонял РОВНО этот текст, а не его
# пересказ (`tests/integration/test_comment_delete_notifications.py`).
PURGE_SQL = sa.text(
    """
    DELETE FROM notifications n
    USING task_comments c
    WHERE c.deleted_at IS NOT NULL
      AND n.kind IN ('task.mentioned', 'task.commented_on_watched')
      AND n.payload->>'task_id' = CAST(c.task_id AS text)
      AND n.created_at = c.created_at
    """
)


def upgrade() -> None:
    # FORCE RLS на обеих таблицах (0013). Роль миграций сегодня superuser и
    # проходит мимо, но полагаться на это нельзя — без флага DELETE молча
    # удалил бы 0 строк (тот же приём, что в 0047).
    op.execute("SET LOCAL app.bypass_rls = 'on'")
    op.execute("SET LOCAL lock_timeout = '5s'")
    purged = op.get_bind().execute(PURGE_SQL).rowcount
    log.info("0064: удалено уведомлений удалённых комментариев: %s", purged)


def downgrade() -> None:
    pass

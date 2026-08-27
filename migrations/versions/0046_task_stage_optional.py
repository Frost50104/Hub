"""Задача может быть без статуса — tasks.stage_id снова nullable

Revision ID: 0046
Revises: 0045
Create Date: 2026-08-25

0044 сделала `stage_id NOT NULL` ради правила «у задачи колонка есть всегда»:
доска должна была показывать каждую задачу. Перенос из WEEEK показал, что
требование было другим: из 16 703 задач 6 386 (38%) в WEEEK не лежали ни в одной
колонке — их вели списком либо колонку с тех пор удалили. Синтетическая колонка
«Без колонки» собрала бы 1 380 карточек из 2 551 в одном проекте и 1 232 из 1 422
в другом, а имя колонки читают глазами и верят ему.

Решение владельца: у задачи есть поле «Статус» с прочерком. Прочерк — это
отсутствие колонки (`NULL`), и такая задача просто не показывается на доске;
появился статус — появилась и карточка.

Остальное из 0044 в силе: колонка — это только имя и позиция, состояние задачи
живёт в `tasks.done`, у проекта по-прежнему ≥1 колонка, а новая задача без явной
колонки уходит в первую (`services/stages.py::require_stage`).

Миграция ОСЛАБЛЯЕТ ограничение, поэтому безопасна в окне деплоя (`deploy.sh`
гоняет alembic до рестарта): старый процесс `NULL` не пишет и на чтении ничего
не теряет. Правило «два деплоя» здесь не работает — оно про `DROP COLUMN` и про
ДОБАВЛЕНИЕ `NOT NULL`.
"""

from __future__ import annotations

from alembic import op

revision: str = "0046"
down_revision: str | None = "0045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tasks ALTER COLUMN stage_id DROP NOT NULL")


def downgrade() -> None:
    # `SET NOT NULL` упадёт на первой же задаче без статуса, а после переноса из
    # WEEEK их тысячи. Поэтому сначала раскладываем их по первой колонке проекта
    # — откат ЛОССИ: «без статуса» и «в первой колонке» после него не различить.
    op.execute(
        """
        UPDATE tasks t
           SET stage_id = (
                 SELECT s.id FROM project_stages s
                  WHERE s.project_id = t.project_id
                  ORDER BY s.position, s.created_at
                  LIMIT 1
               )
         WHERE t.stage_id IS NULL
        """
    )
    op.execute("ALTER TABLE tasks ALTER COLUMN stage_id SET NOT NULL")

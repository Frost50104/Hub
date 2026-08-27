"""Бейдж проекта — эмодзи или картинка вместо двух букв ключа

Revision ID: 0049
Revises: 0048
Create Date: 2026-08-26

Проект рисуется цветным квадратом с двумя буквами ключа
(`web/src/components/project/ProjectKeyChip.tsx`). Теперь он может нести
эмодзи или загруженную картинку. Обе колонки NULL — буквы, как раньше: это
фолбэк, а не «пустое состояние».

Правило ДВУХ ДЕПЛОЁВ здесь НЕ действует: оно про `DROP COLUMN` и про
`NOT NULL` на новой колонке. `ADD COLUMN` нуллябельной и без DEFAULT — только
запись в каталог, таблицу не переписывает; старый процесс колонок не
перечисляет (SQLAlchemy не делает `SELECT *`), а `deploy.sh` рестартует сервис
ПОСЛЕ `alembic upgrade`, то есть новый код видит колонки сразу.

`badge_storage_key` — путь ОТНОСИТЕЛЬНО `attachments_root`, как у
`task_attachments.storage_key` и `media_files.storage_key`. Отдельной таблицы
не заводим: 1:1-опциональный атрибут потребовал бы JOIN в `list_projects`,
который сегодня укладывается в один SELECT в обеих ветках.

Колонки `badge_updated_at` нет намеренно: `projects.updated_at` уже бампается
через `onupdate`, а версию адреса даёт сам `badge_storage_key` — на каждую
заливку в нём свежий uuid.

CHECK на `badge_mime` — не педантизм: этот mime уходит прямо в заголовок
`Content-Type` пользовательских байт, которые отдаются INLINE в `<img>`.
Whitelist на уровне БД означает, что даже баг в ручке не сможет отдать
`text/html`. Цена — добавление gif/avif позже потребует миграции; принято.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0049"
down_revision = "0048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ADD COLUMN и ADD CONSTRAINT берут ACCESS EXCLUSIVE. Таблица крошечная
    # (десятки строк), но лок придётся ждать за `allocate_task_seq`, который
    # держит строку проекта под UPDATE до конца транзакции создания задачи
    # (app/services/tasks.py). Лучше упасть за пять секунд, чем повесить
    # очередь — тот же приём, что в 0045 и 0048.
    op.execute("SET LOCAL lock_timeout = '5s'")

    op.add_column("projects", sa.Column("badge_emoji", sa.String(32), nullable=True))
    op.add_column("projects", sa.Column("badge_storage_key", sa.Text(), nullable=True))
    op.add_column("projects", sa.Column("badge_mime", sa.String(64), nullable=True))

    # Блоб и его тип живут и умирают вместе.
    op.create_check_constraint(
        "ck_projects_badge_image_pair",
        "projects",
        "(badge_storage_key IS NULL) = (badge_mime IS NULL)",
    )
    # Эмодзи ИЛИ картинка. Оба NULL — легально (буквы).
    op.create_check_constraint(
        "ck_projects_badge_exclusive",
        "projects",
        "NOT (badge_emoji IS NOT NULL AND badge_storage_key IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_projects_badge_mime",
        "projects",
        "badge_mime IS NULL OR badge_mime IN ('image/png', 'image/jpeg', 'image/webp')",
    )

    # RLS не трогаем: `projects_rls` создана без FOR-клаузы (0002), то есть
    # FOR ALL, и она колонко-агностична — новые колонки покрыты автоматически.


def downgrade() -> None:
    """Lossy: колонки уйдут, файлы бейджей останутся сиротами на диске.

    Sweeper'а в Hub нет — это зафиксировано в app/services/attachments.py.
    """
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_constraint("ck_projects_badge_mime", "projects", type_="check")
    op.drop_constraint("ck_projects_badge_exclusive", "projects", type_="check")
    op.drop_constraint("ck_projects_badge_image_pair", "projects", type_="check")
    op.drop_column("projects", "badge_mime")
    op.drop_column("projects", "badge_storage_key")
    op.drop_column("projects", "badge_emoji")

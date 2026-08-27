"""Секции переезжают в метки — данные, без удаления сущности

Revision ID: 0047
Revises: 0046
Create Date: 2026-08-25

Секции появились не по замыслу, а из переноса: в WEEEK внутри одного проекта
жило несколько ПАРАЛЛЕЛЬНЫХ досок, в Hub доска одна, и импорт сложил чужие
доски в секции. В результате у задачи оказались две оси группировки — секция
(только во вкладке «Список») и колонка доски, — и их регулярно путают.

Слить оси нельзя: на проде у 1 683 задач из 1 784 стоят обе сразу, уникальных
пар «секция × колонка» — 12 в «Подборе линейного персонала» и 32 во «Вводе/
выводе сотрудников». Поэтому секция становится МЕТКОЙ: «Алена» остаётся
классификацией, колонка остаётся воронкой, обе оси живы. Метка вдобавок видна
во всех представлениях, а не в одном.

Эта миграция ТОЛЬКО переносит данные. `sections` и `tasks.section_id` остаются
на месте: код перестаёт их читать в этом же релизе, а снимаются они следующим
(правило двух деплоёв для `DROP COLUMN`).

Ожидаемо на проде: 34 метки, 1 784 назначения.
"""

from __future__ import annotations

from alembic import op

revision = "0047"
down_revision = "0046"
branch_labels = None
depends_on = None

# Нейтрально-серый, а не дефолтный `#FFB200`: 34 амберных чипа кричали бы, а
# бывшая секция — это классификация, не акцент (docs/DESIGN-SYSTEM.md).
# Контраст текста `lib/labelChip.ts` посчитает сам.
_LABEL_COLOR = "#55556A"

# SQL вынесен в константы, чтобы интеграционный тест гонял РОВНО эти запросы,
# а не их пересказ: главный риск здесь — идемпотентность, и проверять надо
# буквальный текст.
CREATE_LABELS_SQL = f"""
    INSERT INTO task_labels (id, tenant_id, project_id, name, color)
    SELECT gen_random_uuid(), s.tenant_id, s.project_id, s.name, '{_LABEL_COLOR}'
    FROM sections s
    ON CONFLICT (project_id, name) DO NOTHING
"""

# ГЛАВНОЕ МЕСТО. `label_id` берётся JOIN'ом по (project_id, name), а НЕ из
# `RETURNING` предыдущего INSERT'а: при `ON CONFLICT DO NOTHING` строка не
# возвращается, и на повторном прогоне (после упавшего первого) не проставилось
# бы ни одного назначения. Починить это можно было бы только до следующего
# релиза, пока жив `tasks.section_id`.
ASSIGN_LABELS_SQL = """
    INSERT INTO task_label_assignments (task_id, label_id, tenant_id)
    SELECT t.id, l.id, t.tenant_id
    FROM tasks t
    JOIN sections s ON s.id = t.section_id
    JOIN task_labels l
      ON l.project_id = s.project_id AND l.name = s.name
    ON CONFLICT (task_id, label_id) DO NOTHING
"""


def upgrade() -> None:
    # Политики RLS созданы только с `USING`, без `WITH CHECK`, а Postgres в
    # этом случае применяет `USING` и к INSERT. Роль миграций сегодня
    # superuser и проходит мимо, но полагаться на это нельзя — ставим флаг
    # явно, ровно как и рассчитывал 0013.
    op.execute("SET LOCAL app.bypass_rls = 'on'")

    # Имя секции — 255 символов, имя метки — 64. На проде максимум 46, но
    # молча резать чужое имя нельзя: если длинное найдётся, миграция обязана
    # упасть и показать какое.
    op.execute(
        """
        DO $$
        DECLARE bad text;
        BEGIN
            SELECT string_agg(name, ', ') INTO bad
            FROM sections WHERE length(name) > 64;
            IF bad IS NOT NULL THEN
                RAISE EXCEPTION
                    'Имена секций длиннее 64 символов, метка их не вместит: %',
                    bad;
            END IF;
        END $$
        """
    )

    op.execute(CREATE_LABELS_SQL)
    op.execute(ASSIGN_LABELS_SQL)


def downgrade() -> None:
    """Снять ровно те метки, что создала эта миграция.

    Опознаём по паре «имя совпадает с секцией того же проекта» — других
    признаков у метки нет. Метку, которую после миграции переименовали или
    навесили руками на другие задачи, downgrade не тронет: удаляем только
    назначения, у которых есть живая секция-двойник.
    """
    op.execute("SET LOCAL app.bypass_rls = 'on'")

    op.execute(
        """
        DELETE FROM task_label_assignments a
        USING tasks t, sections s, task_labels l
        WHERE a.task_id = t.id
          AND a.label_id = l.id
          AND s.id = t.section_id
          AND l.project_id = s.project_id
          AND l.name = s.name
        """
    )
    op.execute(
        f"""
        DELETE FROM task_labels l
        WHERE l.color = '{_LABEL_COLOR}'
          AND EXISTS (
            SELECT 1 FROM sections s
            WHERE s.project_id = l.project_id AND s.name = l.name
          )
          AND NOT EXISTS (
            SELECT 1 FROM task_label_assignments a WHERE a.label_id = l.id
          )
        """
    )

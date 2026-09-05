"""Увольнение освобождает вход: отвязка уже архивных карточек

Revision ID: 0050
Revises: 0049
Create Date: 2026-09-01

ОС владельца: корпоративный ящик уволенного отдают новому сотруднику, и тот
получает не чистый профиль, а остаток от предшественника — вплоть до сданного
обязательного курса. Матчинг находит карточку по `employee_id` (ящик передали
вместе с учёткой) или по email (учётку пересоздали), и в обоих случаях новый
человек наследует чужую историю.

Лечим отвязкой, а не удалением: на карточке каскадом висят 18 таблиц, среди них
`certificates` и `material_acknowledgements` — доказательство, что сотрудник был
ознакомлен с регламентом. Для общепита это то, что предъявляют проверяющему.

Миграция трогает только ДАННЫЕ: схема не меняется вовсе. Отдельной причины
«уволен» в итоге не завели — любая архивация админом освобождает вход
(`employee_profiles.UNBINDING_REASONS`), потому что выбор «уволен или
временно?» можно ответить неверно каждый раз, а неверный ответ бесшумно
возвращает исходный баг.

Отвязываем уже архивные карточки. Критерий — НЕ причина архивации (у всех стоит
`manual`, и что именно имелось в виду, из данных не видно), а факт: **аккаунт в
auth уже удалён**. Наследовать некому, гадать не о чем. На проде под критерий
попадают 3 карточки из 4 архивных.

Перед отвязкой старый `employee_id` пишется в `audit_log` — иначе откат
превратился бы в сопоставление по email, а email в этом сценарии как раз
переиспользуют. Оттуда же его читает `downgrade`.
"""

from __future__ import annotations

from alembic import op

revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None

# Архивные карточки, чей auth-аккаунт удалён. Один предикат на INSERT и UPDATE,
# чтобы в аудит попало ровно то, что отвязано.
_ORPHANED = """
    p.status = 'archived'
    AND su.employee_id = p.employee_id
    AND su.deleted_at IS NOT NULL
"""


def upgrade() -> None:
    op.execute(
        f"""
        INSERT INTO audit_log
            (tenant_id, actor_id, action, object_type, object_id, object_label, diff)
        SELECT p.tenant_id, NULL, 'update', 'employee_profile', p.id, p.full_name,
               jsonb_build_object(
                   'employee_id',
                       jsonb_build_object('old', p.employee_id::text, 'new', NULL),
                   'migration', '0050'
               )
        FROM employee_profiles p
        JOIN shadow_users su ON su.employee_id = p.employee_id
        WHERE {_ORPHANED}
        """
    )
    op.execute(
        f"""
        UPDATE employee_profiles p
        SET employee_id = NULL
        FROM shadow_users su
        WHERE {_ORPHANED}
        """
    )


def downgrade() -> None:
    # Возвращаем связь по записи, которую сами же и оставили. Если освободившийся
    # `employee_id` успели занять новой карточкой, UPDATE упрётся в unique — это
    # верно: молча перетереть чужую привязку хуже, чем упасть.
    op.execute(
        """
        UPDATE employee_profiles p
        SET employee_id = (a.diff -> 'employee_id' ->> 'old')::uuid
        FROM audit_log a
        WHERE a.object_type = 'employee_profile'
          AND a.object_id = p.id
          AND a.diff ->> 'migration' = '0050'
          AND p.employee_id IS NULL
        """
    )

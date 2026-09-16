"""Вид учётной записи: точка продаж — не ученик

Revision ID: 0056
Revises: 0055
Create Date: 2026-09-16

ОС владельца по экрану «Прогресс сотрудников»: «а почему аккаунты точек вообще
имеют должность продавец-бариста? Мы же вроде в Hub и в auth сделали точки
отдельными сущностями».

Точки отдельной сущностью сделаны — но это ДРУГАЯ сущность. В 0053 завели
реестр объектов (`shadow_sites` + `stores.site_id`), это про физические точки. А
55 спорных карточек — учётные записи касс: обычные `employee_profiles`, которые
с реестром не связаны ничем (в `shadow_sites` нет поля, указывающего на аккаунт;
связь идёт только `site ↔ store`). Должность им вписал человек при HR-импорте —
`staff_sync` `position_id` не трогает вовсе.

Признак у auth есть с 04.09: фид отдаёт `account_kind` (`person` | `service`) и
учётки размечены. Но Hub его ВЫБРАСЫВАЛ — `staff_sync` читал поле в локальную
переменную, принимал по нему одно решение («карточку не создавать») и забывал.
Отличить кассу от бариста сервер не мог: должность у них общая с 214 живыми
баристами, домен `@uppetit.ru` — у 47 настоящих людей, а имя правит человек.

Колонок две, и обе нужны:

- `shadow_users.account_kind` — вид учётки как его знает auth. NULL = синк ещё
  не видел строку; трактуется как `person` (fail-open): обратное означало бы
  «сломался ключ — и все экраны опустели», тот же довод, что у
  `staff_snapshot_fresh`.
- `employee_profiles.account_kind` — вид КАРТОЧКИ, и он же предикат для всего
  learn-домена. На тени его держать нельзя: у одной карточки на проде
  («Кондратьевский, 18») тени нет вовсе — auth про такую учётку не знает, — и
  предикат через `shadow_users` до неё не дотянулся бы никогда. Два независимых
  признака заводить тоже нельзя: именно так карточка окажется исключённой
  наполовину.

Миграция АДДИТИВНАЯ и данные не трогает. Бэкфилл — отдельной джобой
`app/jobs/backfill_account_kind.py` ПОСЛЕ того, как синк заполнит тени: на
момент миграции `shadow_users.account_kind` ещё пуст, и backfill внутри
`upgrade()` проставил бы всем `person`.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0056"
down_revision = "0055"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")

    # Вид учётки как его знает auth. NULL = синк ещё не видел (fail-open).
    op.add_column("shadow_users", sa.Column("account_kind", sa.String(16), nullable=True))

    # Вид карточки. NOT NULL с дефолтом: существующие 313 строк становятся
    # `person`, то есть поведение не меняется до бэкфилла.
    op.add_column(
        "employee_profiles",
        sa.Column(
            "account_kind",
            sa.String(16),
            nullable=False,
            server_default="person",
        ),
    )
    op.create_check_constraint(
        "ck_employee_profiles_account_kind",
        "employee_profiles",
        "account_kind IN ('person', 'service')",
    )
    # Предикат «не касса» стоит в каждом списке learn-домена — индекс частичный,
    # потому что сервисных карточек единицы процентов от таблицы.
    op.create_index(
        "ix_employee_profiles_service",
        "employee_profiles",
        ["tenant_id"],
        postgresql_where=sa.text("account_kind = 'service'"),
    )


def downgrade() -> None:
    op.drop_index("ix_employee_profiles_service", table_name="employee_profiles")
    op.drop_constraint(
        "ck_employee_profiles_account_kind", "employee_profiles", type_="check"
    )
    op.drop_column("employee_profiles", "account_kind")
    op.drop_column("shadow_users", "account_kind")

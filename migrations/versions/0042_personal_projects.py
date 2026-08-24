"""Личное пространство сотрудника — projects.personal_owner_id + бэкфилл «Личное»

Revision ID: 0042
Revises: 0041
Create Date: 2026-08-24

Персональный проект каждого сотрудника: скрыт из всех списков проектов, вход —
секция «ЛИЧНОЕ» на /my. Хранится КОЛОНКОЙ на projects, а не булевым флагом:
участники в личном проекте разрешены, поэтому role='owner' в project_members
перестал определять хозяина однозначно. Partial UNIQUE даёт идемпотентность
ensure_personal_project без приложенческого лока — гонка двух параллельных
/api/me гасится блокировкой на индексе.

Скрытие из списков — ЧИСТО СЕРВЕРНОЕ (app/services/personal_projects.py):
клиентский фильтр не сработал бы у застрявших PWA-бандлов (registerType
'prompt' — старый бандл живёт днями).

ОКНО ДЕПЛОЯ: deploy.sh катит alembic ДО рестарта сервиса, значит между
бэкфиллом и рестартом старый код отдаёт GET /projects без фильтра — каждый на
секунды увидит своё «Личное» в сайдбаре, админ — все. Окно секундное, проекты
пустые. Обратный порядок невозможен: новый код без колонки не стартует.

Бэкфилл — живым shadow_users, которые хоть раз заходили С hub-ролью (у таких
есть employee_profiles; строка в shadow_users заводится на ЛЮБОМ
аутентифицированном запросе, включая юзеров других продуктов Signaris).
Уволенных пропускаем — прецедент 0033 («не воскрешаем проекты давно ушедших»),
при повторном найме заведёт ensure_personal_project на первом входе.
Идемпотентен: NOT EXISTS + ON CONFLICT DO NOTHING, повторный прогон безопасен.

DEFAULT_STAGES скопированы из app/services/stages.py намеренно — миграция
обязана пережить рефакторинг сервиса (так же сделаны 0033 и 0040).

downgrade НЕ удаляет проекты: в них уже могут быть задачи, а каскадное удаление
сотен проектов по `alembic downgrade -1` — необратимая потеря пользовательских
данных. Личные станут обычными и всплывут в списках; чинится накатом обратно.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0042"
down_revision: str | None = "0041"
branch_labels = None
depends_on = None

PERSONAL_NAME = "Личное"
# Транслит «ЛИЧНОЕ»; тот же литерал, что в services/personal_projects.py.
KEY_BASE = "LICNOE"
# Суффикс ТОЛЬКО цифровой: _TASK_KEY_RE ассистента (assistant/context.py) —
# [A-Za-zА-Яа-я0-9]{1,16}, «LICNOE_3F9A-5» перестал бы резолвиться.
KEY_MAX_SUFFIX = 100_000

DEFAULT_STAGES: tuple[tuple[str, str], ...] = (
    ("К выполнению", "todo"),
    ("В работе", "in_progress"),
    ("На проверке", "in_review"),
    ("Готово", "done"),
)

_USERS_SQL = sa.text(
    """
    SELECT su.employee_id, su.tenant_id
    FROM shadow_users su
    WHERE su.deleted_at IS NULL
      AND EXISTS (SELECT 1 FROM employee_profiles ep
                  WHERE ep.employee_id = su.employee_id)
      AND NOT EXISTS (SELECT 1 FROM projects p
                      WHERE p.personal_owner_id = su.employee_id)
    ORDER BY su.tenant_id, su.employee_id
    """
)

_KEYS_SQL = sa.text("SELECT key FROM projects WHERE tenant_id = :t AND key LIKE :p")

_INSERT_PROJECT_SQL = sa.text(
    "INSERT INTO projects (id, tenant_id, key, name, created_by, personal_owner_id) "
    "VALUES (gen_random_uuid(), :t, :k, :n, :e, :e) RETURNING id"
)

_INSERT_STAGE_SQL = sa.text(
    "INSERT INTO project_stages (id, tenant_id, project_id, name, system_status, position) "
    "VALUES (gen_random_uuid(), :t, :p, :n, :s, :pos)"
)

_INSERT_MEMBER_SQL = sa.text(
    "INSERT INTO project_members (id, tenant_id, project_id, employee_id, role, added_by) "
    "VALUES (gen_random_uuid(), :t, :p, :e, 'owner', :e) "
    "ON CONFLICT (project_id, employee_id) DO NOTHING"
)


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column(
            "personal_owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("shadow_users.employee_id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.create_index(
        "uq_projects_personal_owner",
        "projects",
        ["tenant_id", "personal_owner_id"],
        unique=True,
        postgresql_where=sa.text("personal_owner_id IS NOT NULL"),
    )
    _backfill()


def _next_key(used: set[str], cursor: int) -> tuple[str, int]:
    """Первый свободный LICNOE/LICNOE2/… и позиция курсора для следующего."""
    if KEY_BASE not in used:
        return KEY_BASE, cursor
    i = cursor
    while f"{KEY_BASE}{i}" in used:
        i += 1
        if i >= KEY_MAX_SUFFIX:
            raise RuntimeError("personal key space exhausted")
    return f"{KEY_BASE}{i}", i + 1


def _backfill() -> None:
    bind = op.get_bind()
    # Миграции бегут от роли с BYPASSRLS — курсор видит все тенанты. Критично
    # не потерять tenant_id ни в одной вставке: строка с чужим tenant'ом в
    # рантайме fail-closed исчезнет из выдачи без единой ошибки в логах.
    users = bind.execute(_USERS_SQL).all()

    used: dict[str, set[str]] = {}
    cursor: dict[str, int] = {}

    for employee_id, tenant_id in users:
        tkey = str(tenant_id)
        if tkey not in used:
            # Один запрос на тенант, не на человека. LIKE ловит и проект
            # «Личное», заведённый кем-то руками.
            used[tkey] = {
                row[0]
                for row in bind.execute(
                    _KEYS_SQL, {"t": tenant_id, "p": f"{KEY_BASE}%"}
                ).all()
            }
            cursor[tkey] = 2

        key, cursor[tkey] = _next_key(used[tkey], cursor[tkey])
        used[tkey].add(key)

        project_id = bind.execute(
            _INSERT_PROJECT_SQL,
            {"t": tenant_id, "k": key, "n": PERSONAL_NAME, "e": employee_id},
        ).scalar_one()

        # Инвариант «≥1 этап на каждый системный статус» (services/stages.py).
        for position, (name, system_status) in enumerate(DEFAULT_STAGES):
            bind.execute(
                _INSERT_STAGE_SQL,
                {
                    "t": tenant_id,
                    "p": project_id,
                    "n": name,
                    "s": system_status,
                    "pos": position,
                },
            )

        bind.execute(
            _INSERT_MEMBER_SQL, {"t": tenant_id, "p": project_id, "e": employee_id}
        )


def downgrade() -> None:
    op.drop_index("uq_projects_personal_owner", table_name="projects")
    op.drop_column("projects", "personal_owner_id")

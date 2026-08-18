"""Папки проектов: project_folders + projects.folder_id (ОС 17.08)

Revision ID: 0035
Revises: 0034
Create Date: 2026-08-18

Папки ОБЩИЕ для тенанта (атрибут проекта, а не персональная раскладка) и
ровно одного уровня — вложенность потребовала бы проверок циклов и
рекурсивного рендера, а запрос ОС покрывается плоским списком.

`projects.folder_id ON DELETE SET NULL` — механизм, а не «плюс ручная
зачистка»: удаление папки НИКОГДА не удаляет проекты, они переезжают в
«Без папки». RESTRICT («сначала перенесите проекты») отвергнут — запрет на
удаление непустой папки гарантированно вернулся бы тикетом.

ОСОЗНАННОЕ отличие от `sections`: НЕТ UNIQUE(tenant_id, position) DEFERRABLE.
Секциям непрерывность нужна из-за drag-сортировки задач; папкам достаточно
ORDER BY position, lower(name) — совпадающие позиции безвредны, а значит не
нужны ни SET CONSTRAINTS DEFERRED, ни сдвиговые UPDATE.

Уникальность имени — регистронезависимо в рамках тенанта: две «Маркетинг» в
общем для всех дереве неразличимы.

Миграция чисто аддитивная (новая таблица + nullable-колонка) — безопасно
катится до деплоя кода и откатывается.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0035"
down_revision: str | None = "0034"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

RLS_POLICY = (
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid "
    "OR current_setting('app.bypass_rls', true) = 'on'"
)

TABLES: tuple[str, ...] = ("project_folders",)


def upgrade() -> None:
    op.create_table(
        "project_folders",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default=sa.text("0")),
        # SET NULL, а не RESTRICT: папка не должна блокировать удаление
        # сотрудника из shadow_users.
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("shadow_users.employee_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_project_folders_tenant", "project_folders", ["tenant_id"])
    op.create_index(
        "uq_project_folders_tenant_name",
        "project_folders",
        ["tenant_id", sa.text("lower(name)")],
        unique=True,
    )

    op.add_column(
        "projects",
        sa.Column(
            "folder_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("project_folders.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_projects_folder", "projects", ["folder_id"])

    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY {table}_rls ON {table} USING ({RLS_POLICY})")


def downgrade() -> None:
    # Сначала колонка — она держит FK на таблицу.
    op.drop_index("ix_projects_folder", table_name="projects")
    op.drop_column("projects", "folder_id")
    for table in reversed(TABLES):
        op.execute(f"DROP POLICY IF EXISTS {table}_rls ON {table}")
        op.drop_table(table)

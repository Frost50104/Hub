"""Снять колонку и таблицу секций

Revision ID: 0048
Revises: 0047
Create Date: 2026-08-25

Второй деплой после 0047. Разделение обязательно: `DROP COLUMN` берёт
ACCESS EXCLUSIVE, и окно между `alembic upgrade` и рестартом (`deploy.sh`
гоняет их подряд) старый процесс встретил бы с колонкой, которой уже нет.
Плюс 0047 оставил `tasks.section_id` живым специально — чтобы вкладка на
старом бандле, которая шлёт `section_id` при инлайн-создании, доработала до
обновления.

Данные уже переехали в метки (0047) и здесь не трогаются.

Порядок ниже не переставлять: FK `tasks.section_id → sections.id` объявлен
`ON DELETE SET NULL`, и снос таблицы раньше колонки означал бы лишнюю запись
по 1 784 строкам. RLS-политика `sections_rls` уходит вместе с таблицей —
отдельный `DROP POLICY` не нужен.

Downgrade возвращает пустую структуру: разбивку по секциям он не восстановит,
она осталась только в метках. Полный откат — из `pg_dump`, который `deploy.sh`
снимает перед миграцией.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0048"
down_revision = "0047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Лучше упасть за пять секунд, чем повесить очередь запросов к `tasks`
    # за собственным ACCESS EXCLUSIVE (тот же приём, что в 0045).
    op.execute("SET LOCAL lock_timeout = '5s'")

    # Индекс сносим явно, а не полагаемся на каскад от DROP COLUMN: иначе
    # downgrade не знал бы, что его надо вернуть.
    op.drop_index("ix_tasks_section_id", table_name="tasks")
    op.drop_column("tasks", "section_id")
    op.drop_table("sections")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")

    op.create_table(
        "sections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_sections_tenant_id", "sections", ["tenant_id"])
    op.create_index("ix_sections_project_id", "sections", ["project_id"])
    # RLS как у всех доменных таблиц (0002 + FORCE из 0013).
    op.execute("ALTER TABLE sections ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE sections FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY sections_rls ON sections
        USING (
            tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
            OR current_setting('app.bypass_rls', true) = 'on'
        )
        """
    )

    op.add_column(
        "tasks",
        sa.Column(
            "section_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sections.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_tasks_section_id", "tasks", ["section_id"])

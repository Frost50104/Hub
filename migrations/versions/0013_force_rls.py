"""FORCE ROW LEVEL SECURITY на все RLS-таблицы (defense-in-depth)

Без FORCE политики не применяются к владельцу таблицы. Сегодня владелец —
signaris_hub_migrate (superuser, обходит RLS в любом случае), app-роль
не владелец, так что дыры нет. FORCE страхует будущее: смена владельца или
появление не-superuser-владельца не откроет cross-tenant доступ. Политики
содержат `app.bypass_rls` — data-миграции продолжают работать, выставив его.

Revision ID: 0013
Revises: 0012
Create Date: 2026-07-03
"""

from __future__ import annotations

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

# Все tenant-scoped таблицы с RLS-политикой. Намеренно без RLS (и без FORCE):
# shadow_tenants, rate_limits, sync_state, public_share_tokens.
RLS_TABLES: tuple[str, ...] = (
    "shadow_users",
    "projects",
    "project_members",
    "sections",
    "tasks",
    "task_watchers",
    "task_comments",
    "task_labels",
    "task_label_assignments",
    "task_activity",
    "push_subscriptions",
    "notifications",
    "notification_preferences",
    "task_attachments",
    "custom_field_definitions",
    "task_custom_field_values",
    "task_dependencies",
)


def upgrade() -> None:
    for table in RLS_TABLES:
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    for table in RLS_TABLES:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")

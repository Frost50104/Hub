"""Auth — источник штата: кеш роли и статуса учётки + зеркало приглашений

Revision ID: 0052
Revises: 0051
Create Date: 2026-09-02

Админы Hub не могли ответить «кто добавлен и с какой ролью»: продукт узнаёт о
человеке только после его ПЕРВОГО входа (upsert тени на запросе), hub-роли
чужих людей живут только в JWT, а учётка без входа для Hub не существует.
Решение владельца — pull-синк штата из auth (сервисная ручка — хендофф
`docs/handoffs/HUB_TASK_staff_endpoint.md`).

Схема под синк:
- `shadow_users` + `hub_role` (кеш роли продукта — предписанный INTEGRATION.md
  шаг 5b, который Hub не делал; client-lib эти колонки не трогает — её upsert
  обновляет ровно tenant_id/email/full_name/last_seen_at), `auth_active`
  (NULL = синка ещё не было) и `staff_synced_at`;
- `auth_invitations` — зеркало непринятых приглашений с ролью hub: у
  приглашённого нет employee_id, в shadow_users ему места нет, а именно он
  отвечает админу на «добавлен, но ещё не входил».

Аддитивно, «правило двух деплоев» не применяется. RLS на auth_invitations —
в этой же миграции (домашнее правило для tenant-scoped таблиц).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0052"
down_revision = "0051"
branch_labels = None
depends_on = None

RLS_POLICY = (
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid "
    "OR current_setting('app.bypass_rls', true) = 'on'"
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column("shadow_users", sa.Column("hub_role", sa.String(16), nullable=True))
    op.add_column("shadow_users", sa.Column("auth_active", sa.Boolean(), nullable=True))
    op.add_column(
        "shadow_users",
        sa.Column("staff_synced_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "auth_invitations",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True
        ),  # invitation_id из auth — естественный ключ
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=True),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "synced_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.execute("ALTER TABLE auth_invitations ENABLE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY auth_invitations_rls ON auth_invitations USING ({RLS_POLICY})")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_table("auth_invitations")
    op.drop_column("shadow_users", "staff_synced_at")
    op.drop_column("shadow_users", "auth_active")
    op.drop_column("shadow_users", "hub_role")

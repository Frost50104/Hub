"""Персональные настройки интерфейса: user_preferences (тема оформления)

Revision ID: 0054
Revises: 0053
Create Date: 2026-09-09

ОС владельца: на общем устройстве пользователь A выбрал светлую тему, вышел,
вошёл B — и получил тему A. Тема жила ТОЛЬКО в localStorage браузера, то есть
была настройкой устройства, а не человека.

Ключ — `shadow_users.employee_id` (как у `notification_preferences`), а НЕ
`employee_profiles.id`: карточки нет у principal без hub-роли и у архивных
(повторный найм), а тень апсертится на каждом аутентифицированном запросе.
Класть настройку в сам `shadow_users` нельзя — это зеркало auth, его
перестраивает staff-sync.

`theme` NULLABLE и БЕЗ DEFAULT: «строка есть, тему не выбирали» ≠ «выбрал
тёмную». На различии стоит посев темы из localStorage при первом входе после
выката — с `DEFAULT 'dark'` он записал бы тёмную всем подряд.

Миграция чисто аддитивная (новая таблица) — безопасно катится до деплоя кода.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0054"
down_revision: str | None = "0053"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

RLS_POLICY = (
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid "
    "OR current_setting('app.bypass_rls', true) = 'on'"
)

TABLE = "user_preferences"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table(
        TABLE,
        sa.Column(
            "employee_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("shadow_users.employee_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("theme", sa.String(8), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "theme IS NULL OR theme IN ('light', 'dark')",
            name="ck_user_preferences_theme",
        ),
    )
    op.create_index(f"ix_{TABLE}_tenant", TABLE, ["tenant_id"])

    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY {TABLE}_rls ON {TABLE} USING ({RLS_POLICY})")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(f"DROP POLICY IF EXISTS {TABLE}_rls ON {TABLE}")
    op.drop_index(f"ix_{TABLE}_tenant", table_name=TABLE)
    op.drop_table(TABLE)

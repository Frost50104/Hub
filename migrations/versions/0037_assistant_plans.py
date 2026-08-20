"""Ассистент, волна 1: журнал операций и планы действий

Revision ID: 0037
Revises: 0036
Create Date: 2026-08-20

Ассистент из макетов Claude Design перестаёт быть чатом по базе знаний и
становится общим для двух пространств. Отсюда три изменения:

1. `ai_conversations.employee_id` — диалог принадлежит СОТРУДНИКУ
   (`shadow_users`), а не учебному профилю. Прежняя привязка нарушала
   FK-инвариант проекта («действует человек → shadow_users; данные О человеке
   → employee_profiles») и практически ломала фичу: `get_profile` ищет строку
   в `employee_profiles`, которой у пользователя-только-трекера нет, и
   ассистент отвечал бы ему 404 «Профиль не найден». `profile_id` остаётся
   (retrieval базы знаний фильтрует по аудитории именно по нему), но
   становится nullable.

2. `ai_messages.kind` + `data` — журнал операций вместо ленты реплик. Роль
   в БД по-прежнему `user|assistant`: CHECK не трогаем, роль `tool` живёт
   только в памяти рантайма, история для модели пересобирается из kind+data.

3. `ai_plans` — предложенное действие, ожидающее подтверждения человеком.
   Порог: правки выполняются сразу, создание и архивация — всегда через план.
   `expires_at` обязателен: между показом плана и «Выполнить» мир меняется,
   и исполнять получасовой план вслепую нельзя (права всё равно
   перепроверяются на исполнении).

Backfill employee_id: у существующих диалогов Ф6 он выводится из
`employee_profiles.employee_id`. Строки без связи (профиль ещё не входил в
Hub) удаляются — это диалоги, которые всё равно некому показать.

ENABLE + FORCE RLS на новую таблицу.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0037"
down_revision: str | None = "0036"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

RLS_POLICY = (
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid "
    "OR current_setting('app.bypass_rls', true) = 'on'"
)


def upgrade() -> None:
    # ── 1. Диалог принадлежит сотруднику ────────────────────────────────
    op.add_column(
        "ai_conversations",
        sa.Column("employee_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.execute(
        "UPDATE ai_conversations c SET employee_id = p.employee_id "
        "FROM employee_profiles p "
        "WHERE p.id = c.profile_id AND p.employee_id IS NOT NULL"
    )
    op.execute("DELETE FROM ai_conversations WHERE employee_id IS NULL")
    op.alter_column("ai_conversations", "employee_id", nullable=False)
    op.create_foreign_key(
        "fk_ai_conversations_employee",
        "ai_conversations",
        "shadow_users",
        ["employee_id"],
        ["employee_id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_ai_conversations_employee_id", "ai_conversations", ["employee_id"]
    )
    op.alter_column("ai_conversations", "profile_id", nullable=True)

    # ── 2. Журнал операций ──────────────────────────────────────────────
    op.add_column(
        "ai_messages",
        sa.Column(
            "kind",
            sa.String(16),
            nullable=False,
            server_default="answer",
        ),
    )
    op.add_column("ai_messages", sa.Column("data", postgresql.JSONB(), nullable=True))
    op.create_check_constraint(
        "ck_ai_messages_kind",
        "ai_messages",
        "kind IN ('answer', 'summary', 'action', 'report', 'error', 'denied')",
    )

    # ── 3. Планы действий ───────────────────────────────────────────────
    op.create_table(
        "ai_plans",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ai_conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Сообщение журнала, в котором нарисована карточка. Nullable и
        # SET NULL: план создаётся ДО сообщения (id нужен в его data).
        sa.Column(
            "message_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ai_messages.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "employee_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("shadow_users.employee_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tool", sa.String(64), nullable=False),
        # Аргументы инструмента после pydantic-валидации — исполняется
        # ИМЕННО это, а не то, что пришлёт клиент.
        sa.Column("args", postgresql.JSONB(), nullable=False),
        # Человекочитаемая карточка: поля, заголовок, счётчик объектов.
        sa.Column("preview", postgresql.JSONB(), nullable=False),
        sa.Column("steps", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'done', 'rejected', 'failed')",
            name="ck_ai_plans_status",
        ),
    )
    op.create_index("ix_ai_plans_tenant_id", "ai_plans", ["tenant_id"])
    op.create_index("ix_ai_plans_conversation_id", "ai_plans", ["conversation_id"])

    op.execute("ALTER TABLE ai_plans ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ai_plans FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY ai_plans_rls ON ai_plans USING ({RLS_POLICY})")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS ai_plans_rls ON ai_plans")
    op.drop_table("ai_plans")

    op.drop_constraint("ck_ai_messages_kind", "ai_messages", type_="check")
    op.drop_column("ai_messages", "data")
    op.drop_column("ai_messages", "kind")

    # profile_id обратно NOT NULL: диалоги без учебного профиля (их и создаёт
    # ассистент после этой ревизии) откатить нечем — удаляем.
    op.execute("DELETE FROM ai_conversations WHERE profile_id IS NULL")
    op.alter_column("ai_conversations", "profile_id", nullable=False)
    op.drop_index("ix_ai_conversations_employee_id", table_name="ai_conversations")
    op.drop_constraint(
        "fk_ai_conversations_employee", "ai_conversations", type_="foreignkey"
    )
    op.drop_column("ai_conversations", "employee_id")

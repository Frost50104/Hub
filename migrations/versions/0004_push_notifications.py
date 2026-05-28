"""push_subscriptions + notifications + notification_preferences + RLS

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


RLS_POLICY = (
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid "
    "OR current_setting('app.bypass_rls', true) = 'on'"
)


def upgrade() -> None:
    # ─── push_subscriptions ─────────────────────────────────────────────────
    op.create_table(
        "push_subscriptions",
        sa.Column(
            "id", sa.BigInteger, sa.Identity(always=True), primary_key=True
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "employee_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("shadow_users.employee_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("endpoint", sa.Text, nullable=False, unique=True),
        sa.Column("p256dh", sa.Text, nullable=False),
        sa.Column("auth", sa.String(64), nullable=False),
        sa.Column("user_agent", sa.String(256), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_push_subscriptions_tenant_id", "push_subscriptions", ["tenant_id"]
    )
    op.create_index(
        "ix_push_subscriptions_employee_id", "push_subscriptions", ["employee_id"]
    )
    op.execute("ALTER TABLE push_subscriptions ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY push_subscriptions_rls ON push_subscriptions USING ({RLS_POLICY})"
    )

    # ─── notifications (in-app inbox) ───────────────────────────────────────
    op.create_table(
        "notifications",
        sa.Column(
            "id", sa.BigInteger, sa.Identity(always=True), primary_key=True
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "employee_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("shadow_users.employee_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("url", sa.String(512), nullable=True),
        sa.Column("payload", postgresql.JSONB, nullable=True),
        sa.Column(
            "is_read",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_notifications_tenant_id", "notifications", ["tenant_id"])
    op.create_index("ix_notifications_employee_id", "notifications", ["employee_id"])
    op.create_index(
        "ix_notifications_employee_created",
        "notifications",
        ["employee_id", "created_at"],
    )
    op.execute("ALTER TABLE notifications ENABLE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY notifications_rls ON notifications USING ({RLS_POLICY})")

    # ─── notification_preferences ───────────────────────────────────────────
    op.create_table(
        "notification_preferences",
        sa.Column(
            "employee_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("shadow_users.employee_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "prefs",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_notification_preferences_tenant_id",
        "notification_preferences",
        ["tenant_id"],
    )
    op.execute("ALTER TABLE notification_preferences ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY notification_preferences_rls ON notification_preferences "
        f"USING ({RLS_POLICY})"
    )


def downgrade() -> None:
    for table in ("notification_preferences", "notifications", "push_subscriptions"):
        op.execute(f"DROP POLICY IF EXISTS {table}_rls ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.drop_table("notification_preferences")
    op.drop_table("notifications")
    op.drop_table("push_subscriptions")

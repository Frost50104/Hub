"""Рейтинг активности + сертификаты (LMS Ф3b)

Revision ID: 0025
Revises: 0024
Create Date: 2026-07-18

activity_events — append-only (политики только SELECT+INSERT, как audit_log)
+ partial-unique «первое действие». certificates — обычный RLS.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

RLS_POLICY = (
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid "
    "OR current_setting('app.bypass_rls', true) = 'on'"
)


def upgrade() -> None:
    op.create_table(
        "activity_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "profile_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("employee_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("object_type", sa.String(32), nullable=False),
        sa.Column("object_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("points", sa.Numeric(6, 2), nullable=False),
        sa.Column("meta", postgresql.JSONB(), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_activity_events_tenant", "activity_events", ["tenant_id"])
    op.create_index("ix_activity_events_profile", "activity_events", ["profile_id"])
    op.create_index("ix_activity_events_occurred", "activity_events", ["occurred_at"])
    # «Первое действие»: одно начисление за (профиль, событие, объект).
    op.execute(
        "CREATE UNIQUE INDEX uq_activity_events_first ON activity_events "
        "(tenant_id, profile_id, event_type, object_type, object_id)"
    )

    op.create_table(
        "certificates",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "profile_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("employee_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "course_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("serial", sa.String(32), nullable=False),
        sa.Column("course_title", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column(
            "issued_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("course_id", "profile_id", name="uq_certificates_course_profile"),
        sa.UniqueConstraint("tenant_id", "serial", name="uq_certificates_serial"),
    )
    op.create_index("ix_certificates_tenant", "certificates", ["tenant_id"])
    op.create_index("ix_certificates_profile", "certificates", ["profile_id"])

    # activity_events — append-only.
    op.execute("ALTER TABLE activity_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE activity_events FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY activity_events_select ON activity_events FOR SELECT USING ({RLS_POLICY})"
    )
    op.execute(
        f"CREATE POLICY activity_events_insert ON activity_events "
        f"FOR INSERT WITH CHECK ({RLS_POLICY})"
    )

    op.execute("ALTER TABLE certificates ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE certificates FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY certificates_rls ON certificates USING ({RLS_POLICY})")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS certificates_rls ON certificates")
    op.drop_table("certificates")
    op.execute("DROP POLICY IF EXISTS activity_events_select ON activity_events")
    op.execute("DROP POLICY IF EXISTS activity_events_insert ON activity_events")
    op.drop_table("activity_events")

"""Аттестации: кампании поверх движка тестов (LMS Ф8)

Revision ID: 0030
Revises: 0029
Create Date: 2026-07-19

quizzes.course_id становится nullable + добавляется campaign_id:
CHECK гарантирует ровно одного владельца (курс XOR кампания).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

RLS_POLICY = (
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid "
    "OR current_setting('app.bypass_rls', true) = 'on'"
)


def upgrade() -> None:
    op.create_table(
        "assessment_campaigns",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "audience_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("audiences.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'draft'")),
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
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'closed')",
            name="ck_assessment_campaigns_status",
        ),
    )
    op.create_index("ix_assessment_campaigns_tenant", "assessment_campaigns", ["tenant_id"])
    op.create_index("ix_assessment_campaigns_status", "assessment_campaigns", ["status"])

    op.execute("ALTER TABLE assessment_campaigns ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE assessment_campaigns FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY assessment_campaigns_rls ON assessment_campaigns USING ({RLS_POLICY})"
    )

    # Quiz: владелец — курс ИЛИ кампания.
    op.alter_column("quizzes", "course_id", nullable=True)
    op.add_column(
        "quizzes",
        sa.Column(
            "campaign_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "assessment_campaigns.id",
                ondelete="CASCADE",
                name="fk_quizzes_campaign",
            ),
            nullable=True,
        ),
    )
    op.create_index("ix_quizzes_campaign", "quizzes", ["campaign_id"])
    op.create_check_constraint(
        "ck_quizzes_owner",
        "quizzes",
        "(course_id IS NULL) != (campaign_id IS NULL)",
    )
    # Одна кампания — один квиз.
    op.execute(
        "CREATE UNIQUE INDEX uq_quizzes_campaign ON quizzes (campaign_id) "
        "WHERE campaign_id IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_constraint("ck_quizzes_owner", "quizzes", type_="check")
    op.execute("DROP INDEX IF EXISTS uq_quizzes_campaign")
    op.drop_index("ix_quizzes_campaign", table_name="quizzes")
    op.drop_column("quizzes", "campaign_id")
    op.execute("DELETE FROM quizzes WHERE course_id IS NULL")
    op.alter_column("quizzes", "course_id", nullable=False)
    op.execute("DROP POLICY IF EXISTS assessment_campaigns_rls ON assessment_campaigns")
    op.drop_table("assessment_campaigns")

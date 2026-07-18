"""Тесты уроков/курсов: quizzes, quiz_questions, quiz_attempts (LMS Ф3b)

Revision ID: 0024
Revises: 0023
Create Date: 2026-07-18

ENABLE + FORCE RLS на всех.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

RLS_POLICY = (
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid "
    "OR current_setting('app.bypass_rls', true) = 'on'"
)

TABLES: tuple[str, ...] = ("quizzes", "quiz_questions", "quiz_attempts")


def upgrade() -> None:
    op.create_table(
        "quizzes",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "course_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "lesson_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("course_lessons.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'draft'")),
        sa.Column(
            "pass_score_pct", sa.Integer(), nullable=False, server_default=sa.text("80")
        ),
        sa.Column("attempts_limit", sa.Integer(), nullable=True),
        sa.Column(
            "shuffle_questions", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "shuffle_options", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "show_correct_answers",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("is_required", sa.Boolean(), nullable=False, server_default=sa.text("true")),
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
        sa.CheckConstraint("status IN ('draft', 'published')", name="ck_quizzes_status"),
        sa.CheckConstraint(
            "pass_score_pct >= 1 AND pass_score_pct <= 100", name="ck_quizzes_pass_score"
        ),
        sa.UniqueConstraint("lesson_id", name="uq_quizzes_lesson"),
    )
    op.create_index("ix_quizzes_tenant", "quizzes", ["tenant_id"])
    op.create_index("ix_quizzes_course", "quizzes", ["course_id"])
    # Один финальный тест на курс (lesson_id IS NULL).
    op.execute(
        "CREATE UNIQUE INDEX uq_quizzes_course_final ON quizzes (course_id) "
        "WHERE lesson_id IS NULL"
    )

    op.create_table(
        "quiz_questions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "quiz_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("quizzes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("qtype", sa.String(8), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column(
            "media_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("media_files.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "options", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("answer", postgresql.JSONB(), nullable=True),
        sa.Column("points", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.CheckConstraint(
            "qtype IN ('single', 'multi', 'open', 'match', 'order')",
            name="ck_quiz_questions_qtype",
        ),
        sa.CheckConstraint("points >= 1", name="ck_quiz_questions_points"),
    )
    op.create_index("ix_quiz_questions_tenant", "quiz_questions", ["tenant_id"])
    op.create_index("ix_quiz_questions_quiz", "quiz_questions", ["quiz_id"])

    op.create_table(
        "quiz_attempts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "quiz_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("quizzes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "profile_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("employee_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column(
            "snapshot", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column(
            "answers", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("score_pct", sa.Integer(), nullable=True),
        sa.Column("passed", sa.Boolean(), nullable=True),
        sa.Column(
            "needs_review", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("review_scores", postgresql.JSONB(), nullable=True),
        sa.Column(
            "reviewed_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("shadow_users.employee_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("quiz_id", "profile_id", "attempt_no", name="uq_quiz_attempts_no"),
    )
    op.create_index("ix_quiz_attempts_tenant", "quiz_attempts", ["tenant_id"])
    op.create_index("ix_quiz_attempts_quiz", "quiz_attempts", ["quiz_id"])
    op.create_index("ix_quiz_attempts_profile", "quiz_attempts", ["profile_id"])
    # Очередь ревью HR: pending-попытки ищутся по needs_review.
    op.execute(
        "CREATE INDEX ix_quiz_attempts_review ON quiz_attempts (tenant_id, finished_at) "
        "WHERE needs_review AND reviewed_at IS NULL"
    )

    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY {table}_rls ON {table} USING ({RLS_POLICY})")


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f"DROP POLICY IF EXISTS {table}_rls ON {table}")
        op.drop_table(table)

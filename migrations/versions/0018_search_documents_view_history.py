"""Единый поисковый индекс + очередь извлечения текста + история просмотров (Ф1)

Revision ID: 0018
Revises: 0017
Create Date: 2026-07-17

- search_documents: одна строка на published-объект; search_vector — STORED
  GENERATED tsvector (russian; title=A, snippet=B, body=C) + GIN, по образцу
  0008. Наполняется только сервисом search_indexer (черновики не индексируются).
- text_extraction_jobs: каркас очереди извлечения текста из файлов
  (воркер — 2-я волна, отдельный systemd-процесс).
- view_history: первое/последнее открытие (гейт «Ознакомлен», перенесена
  из Ф2 — adversarial-ревью §24).

ENABLE + FORCE RLS на всех.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

RLS_POLICY = (
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid "
    "OR current_setting('app.bypass_rls', true) = 'on'"
)

TABLES: tuple[str, ...] = ("search_documents", "text_extraction_jobs", "view_history")


def upgrade() -> None:
    op.create_table(
        "search_documents",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("object_type", sa.String(32), nullable=False),
        sa.Column("object_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("snippet", sa.Text(), nullable=True),
        sa.Column("body_text", sa.Text(), nullable=True),
        sa.Column(
            "audience_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("audiences.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("url_path", sa.String(512), nullable=False),
        sa.UniqueConstraint("object_type", "object_id", name="uq_search_documents_object"),
    )
    op.create_index("ix_search_documents_tenant", "search_documents", ["tenant_id"])
    op.create_index(
        "ix_search_documents_tenant_published",
        "search_documents",
        ["tenant_id", "published_at"],
    )
    # STORED GENERATED tsvector — как tasks.search_vector в 0008.
    op.execute(
        """
        ALTER TABLE search_documents ADD COLUMN search_vector tsvector
        GENERATED ALWAYS AS (
            setweight(to_tsvector('russian', coalesce(title, '')), 'A') ||
            setweight(to_tsvector('russian', coalesce(snippet, '')), 'B') ||
            setweight(to_tsvector('russian', coalesce(body_text, '')), 'C')
        ) STORED
        """
    )
    op.execute(
        "CREATE INDEX ix_search_documents_vector ON search_documents "
        "USING gin (search_vector)"
    )

    op.create_table(
        "text_extraction_jobs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("object_type", sa.String(32), nullable=False),
        sa.Column("object_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("storage_key", sa.String(512), nullable=False),
        sa.Column("mime", sa.String(128), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("error", sa.Text(), nullable=True),
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
            "status IN ('pending', 'done', 'failed')", name="ck_text_extraction_jobs_status"
        ),
    )
    op.create_index("ix_text_extraction_jobs_tenant", "text_extraction_jobs", ["tenant_id"])
    op.create_index("ix_text_extraction_jobs_status", "text_extraction_jobs", ["status"])

    op.create_table(
        "view_history",
        sa.Column(
            "profile_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("employee_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("object_type", sa.String(32), nullable=False),
        sa.Column("object_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "first_viewed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "last_viewed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("view_count", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.PrimaryKeyConstraint("profile_id", "object_type", "object_id", name="pk_view_history"),
    )
    op.create_index("ix_view_history_tenant", "view_history", ["tenant_id"])
    op.create_index("ix_view_history_object", "view_history", ["object_type", "object_id"])

    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY {table}_rls ON {table} USING ({RLS_POLICY})")


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f"DROP POLICY IF EXISTS {table}_rls ON {table}")
        op.drop_table(table)

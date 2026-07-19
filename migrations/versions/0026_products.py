"""Ассортимент: категории, карточки товаров, связи с обучением (LMS Ф4)

Revision ID: 0026
Revises: 0025
Create Date: 2026-07-19

ENABLE + FORCE RLS на всех.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

RLS_POLICY = (
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid "
    "OR current_setting('app.bypass_rls', true) = 'on'"
)

TABLES: tuple[str, ...] = ("product_categories", "product_cards", "product_card_links")


def upgrade() -> None:
    op.create_table(
        "product_categories",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_product_categories_tenant", "product_categories", ["tenant_id"])

    op.create_table(
        "product_cards",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "category_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("product_categories.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "audience_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("audiences.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "photos", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column("composition", sa.Text(), nullable=True),
        sa.Column("allergens", sa.Text(), nullable=True),
        sa.Column("shelf_life", sa.Text(), nullable=True),
        sa.Column("serving", sa.Text(), nullable=True),
        sa.Column("upsell", sa.Text(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default=sa.text("0")),
        # ContentLifecycleMixin
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'draft'")),
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("shadow_users.employee_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("shadow_users.employee_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_period_months", sa.Integer(), nullable=True),
        sa.Column("next_review_at", sa.DateTime(timezone=True), nullable=True),
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
            "status IN ('draft', 'review', 'published', 'archived')",
            name="ck_product_cards_status",
        ),
    )
    op.create_index("ix_product_cards_tenant", "product_cards", ["tenant_id"])
    op.create_index("ix_product_cards_status", "product_cards", ["status"])
    op.create_index("ix_product_cards_category", "product_cards", ["category_id"])

    op.create_table(
        "product_card_links",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "product_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("product_cards.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("object_type", sa.String(16), nullable=False),
        sa.Column("object_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.CheckConstraint(
            "object_type IN ('course', 'lesson', 'material')",
            name="ck_product_card_links_type",
        ),
    )
    op.create_index("ix_product_card_links_tenant", "product_card_links", ["tenant_id"])
    op.create_index("ix_product_card_links_product", "product_card_links", ["product_id"])

    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY {table}_rls ON {table} USING ({RLS_POLICY})")


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f"DROP POLICY IF EXISTS {table}_rls ON {table}")
        op.drop_table(table)

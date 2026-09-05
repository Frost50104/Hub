"""Зеркало реестра объектов auth: shadow_sites + stores.site_id

Revision ID: 0053
Revises: 0052
Create Date: 2026-09-05

Auth завёл единый справочник торговых точек (`sites`) и засеял его разметкой
человека (хендофф docs/handoffs/HUB_TASK_sites_mirror.md). Hub получает:
- `stores.site_id` — nullable UUID БЕЗ FK (ссылка межбазовая, FK невозможен;
  тот же паттерн, что employee_id -> auth). Заполняется НЕ синхронизацией и
  НЕ API, а разовым бэкфиллом из файла связей (выкат 2);
- `shadow_sites` — зеркало снимка `GET /api/products/sites` под обычной
  per-tenant RLS. `refs` — JSONB-массив внешних ссылок объекта
  ({system, external_id}); у одного объекта может быть НЕСКОЛЬКО ссылок
  system="hub" — это наши дубли, ради их слияния реестр и заводился.

Аддитивно, «правило двух деплоев» не применяется. Порядок ОТКАТА прод-данных:
сначала docs/handoffs/uppetit_sites_rollback.sql (site_id -> NULL, очистка
зеркала), только потом downgrade — id реестра не должны переживать дроп.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0053"
down_revision = "0052"
branch_labels = None
depends_on = None

RLS_POLICY = (
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid "
    "OR current_setting('app.bypass_rls', true) = 'on'"
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column(
        "stores",
        sa.Column("site_id", postgresql.UUID(as_uuid=True), nullable=True),
    )

    op.create_table(
        "shadow_sites",
        sa.Column(
            "site_id", postgresql.UUID(as_uuid=True), primary_key=True
        ),  # id объекта в реестре auth — естественный ключ
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("code", sa.String(32), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("legal_name", sa.String(255), nullable=True),
        sa.Column("inn", sa.String(32), nullable=True),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("phone", sa.String(64), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "refs",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.execute("ALTER TABLE shadow_sites ENABLE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY shadow_sites_rls ON shadow_sites USING ({RLS_POLICY})")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("DROP POLICY IF EXISTS shadow_sites_rls ON shadow_sites")
    op.drop_table("shadow_sites")
    op.drop_column("stores", "site_id")

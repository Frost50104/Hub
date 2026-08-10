"""Аудитории: измерение «контур» (org_roles) в правилах (ОС 2026-08-10)

Revision ID: 0031
Revises: 0030
Create Date: 2026-08-10

Аддитивная nullable-колонка text[] на audience_rules — «весь офис» /
«все франчайзи» без перечисления отделов/франчайзи поимённо. Значения —
из ORG_ROLES (employee | tu | franchisee_owner | office), валидация на API.
RLS-политики 0015 построчные (tenant_id) — новую колонку покрывают как есть.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.add_column(
        "audience_rules",
        sa.Column("org_roles", postgresql.ARRAY(sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("audience_rules", "org_roles")

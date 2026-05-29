"""public_share_tokens: view-only deep-links без логина (3.6.12)

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-29

A view-only public link to a task or project. Anonymous reader resolves
`/p/<token>` → `/api/public/<token>` → sanitized payload (initials only,
никаких email/employee_id/tenant_slug/attachment-download-URL).

**Без RLS.** Auth-страница нашего фронтенда не знает текущего tenant_id
(посетитель НЕ авторизован), а endpoint ищет токен cross-tenant. Security
основан на UUID v4 entropy (122 бита) + явный `bypass_rls=True` *только*
внутри одного handler'а после успешного lookup.

Revoke = `revoked_at = now()`; expires = `expires_at`. Запросы фильтруют по
обоим: `WHERE revoked_at IS NULL AND (expires_at IS NULL OR expires_at > now())`.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "public_share_tokens",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "token",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            unique=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("shadow_users.employee_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "scope IN ('task','project')",
            name="ck_public_share_tokens_scope",
        ),
    )
    # Partial index — list_for_entity uses this; revoked tokens stay in the
    # table for auditing but drop out of `WHERE revoked_at IS NULL` queries.
    op.create_index(
        "ix_pst_entity_active",
        "public_share_tokens",
        ["scope", "entity_id"],
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_index("ix_pst_tenant", "public_share_tokens", ["tenant_id"])
    # NO RLS: cross-tenant lookup by token is intended. Tenant scoping happens
    # in the handler after the token resolves.


def downgrade() -> None:
    op.drop_index("ix_pst_tenant", table_name="public_share_tokens")
    op.drop_index("ix_pst_entity_active", table_name="public_share_tokens")
    op.drop_table("public_share_tokens")

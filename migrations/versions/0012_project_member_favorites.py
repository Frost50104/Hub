"""project_members.is_favorite — избранные проекты (personal, per-member)

Флаг живёт на строке членства: избранное у каждого участника своё.
RLS на project_members уже включён в 0002 — новых политик не нужно.

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.add_column(
        "project_members",
        sa.Column(
            "is_favorite",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("project_members", "is_favorite")

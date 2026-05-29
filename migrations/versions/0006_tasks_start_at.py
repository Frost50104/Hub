"""tasks.start_at + range index for Calendar view (3.6.9)

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-29

Adds a nullable `start_at` so multi-day tasks span N cells in the calendar
grid (single-day tasks leave it NULL and are pinned to due_at only). The
range-index makes the calendar endpoint's overlap query (`start_at <= to
AND due_at >= from`) a cheap index scan.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Range overlap (start_at <= :to AND due_at >= :from) — composite GIST would be
    # ideal, but two btrees + NULL-safe filter is good enough at our scale and
    # doesn't need the btree_gist extension.
    op.create_index(
        "ix_tasks_start_at",
        "tasks",
        ["start_at"],
        postgresql_where=sa.text("archived_at IS NULL"),
    )
    op.create_index(
        "ix_tasks_due_at",
        "tasks",
        ["due_at"],
        postgresql_where=sa.text("archived_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_tasks_due_at", table_name="tasks")
    op.drop_index("ix_tasks_start_at", table_name="tasks")
    op.drop_column("tasks", "start_at")

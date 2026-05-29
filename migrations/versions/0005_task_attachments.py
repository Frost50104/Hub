"""task_attachments + RLS

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


RLS_POLICY = (
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid "
    "OR current_setting('app.bypass_rls', true) = 'on'"
)


def upgrade() -> None:
    op.create_table(
        "task_attachments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "uploaded_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("shadow_users.employee_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("mime", sa.String(128), nullable=False),
        sa.Column("size_bytes", sa.BigInteger, nullable=False),
        sa.Column("storage_key", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_task_attachments_tenant_id", "task_attachments", ["tenant_id"])
    op.create_index("ix_task_attachments_task_id", "task_attachments", ["task_id"])
    op.execute("ALTER TABLE task_attachments ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY task_attachments_rls ON task_attachments USING ({RLS_POLICY})"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS task_attachments_rls ON task_attachments")
    op.execute("ALTER TABLE task_attachments DISABLE ROW LEVEL SECURITY")
    op.drop_table("task_attachments")

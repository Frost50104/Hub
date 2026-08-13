"""Backfill viewer-членства для исполнителей задач без membership

Revision ID: 0033
Revises: 0032
Create Date: 2026-08-13

Исполнителем можно назначить любого сотрудника тенанта, а /api/me/tasks
не фильтрует по членству — назначенный не-член видел задачу в «Все задачи»,
но deep-link в проект давал 404. С этого релиза назначение создаёт
viewer-членство на лету (project_access.ensure_project_member); здесь —
разовый backfill для уже существующих назначений.

Только незаархивированные задачи (не «воскрешаем» старые проекты в сайдбарах
давно ушедших исполнителей) и живые сотрудники (deleted_at IS NULL).
tenant_id — из projects (source of truth). Идемпотентно (ON CONFLICT
DO NOTHING); существующие роли не понижаются. Data-only: downgrade — no-op
(авто-строки постфактум неотличимы от ручных).
"""

from __future__ import annotations

from alembic import op

revision: str = "0033"
down_revision: str | None = "0032"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO project_members
            (id, tenant_id, project_id, employee_id, role, added_by, added_at)
        SELECT gen_random_uuid(), sub.tenant_id, sub.project_id, sub.assignee_id,
               'viewer', NULL, now()
        FROM (
            SELECT DISTINCT p.tenant_id, t.project_id, t.assignee_id
            FROM tasks t
            JOIN projects p ON p.id = t.project_id
            JOIN shadow_users su
              ON su.employee_id = t.assignee_id AND su.deleted_at IS NULL
            WHERE t.assignee_id IS NOT NULL
              AND t.archived_at IS NULL
        ) sub
        ON CONFLICT (project_id, employee_id) DO NOTHING
        """
    )


def downgrade() -> None:
    pass

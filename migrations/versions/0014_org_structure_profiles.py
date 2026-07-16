"""Оргструктура + HR-профили сотрудников (LMS Ф0, ТЗ §2.1/§17)

Revision ID: 0014
Revises: 0013
Create Date: 2026-07-16

Справочники (должности/магазины/франчайзи + их группы, отделы-дерево,
пользовательские группы) и центральная HR-карточка `employee_profiles`
поверх shadow_users (`employee_id` NULL до первого входа, матчинг по email).

Уникальность:
- имена архивируемых справочников — partial unique только по активным
  (архив не блокирует повторное имя);
- email профиля — partial unique по lower(email) среди active (защита от
  гонки первого входа и дублей при повторном найме).

Все таблицы — ENABLE + FORCE RLS сразу (пост-0013 порядок).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

RLS_POLICY = (
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid "
    "OR current_setting('app.bypass_rls', true) = 'on'"
)

TABLES: tuple[str, ...] = (
    "positions",
    "position_groups",
    "position_group_members",
    "franchisees",
    "franchisee_groups",
    "franchisee_group_members",
    "stores",
    "store_groups",
    "store_group_members",
    "departments",
    "employee_profiles",
    "tu_store_assignments",
    "user_groups",
    "user_group_members",
)


def _uuid_pk() -> sa.Column:
    return sa.Column(
        "id",
        postgresql.UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )


def _tenant() -> sa.Column:
    return sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False)


def _created_at() -> sa.Column:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )


def upgrade() -> None:
    # --- Справочники -------------------------------------------------------
    op.create_table(
        "positions",
        _uuid_pk(),
        _tenant(),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
    )
    op.create_index("ix_positions_tenant", "positions", ["tenant_id"])
    op.create_index(
        "uq_positions_active_name",
        "positions",
        ["tenant_id", sa.text("lower(name)")],
        unique=True,
        postgresql_where=sa.text("archived_at IS NULL"),
    )

    op.create_table(
        "position_groups",
        _uuid_pk(),
        _tenant(),
        sa.Column("name", sa.String(255), nullable=False),
        _created_at(),
    )
    op.create_index("ix_position_groups_tenant", "position_groups", ["tenant_id"])

    op.create_table(
        "position_group_members",
        _uuid_pk(),
        _tenant(),
        sa.Column(
            "group_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("position_groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "position_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("positions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.UniqueConstraint("group_id", "position_id", name="uq_position_group_members"),
    )
    op.create_index("ix_position_group_members_tenant", "position_group_members", ["tenant_id"])
    op.create_index("ix_position_group_members_group", "position_group_members", ["group_id"])
    op.create_index(
        "ix_position_group_members_position", "position_group_members", ["position_id"]
    )

    op.create_table(
        "franchisees",
        _uuid_pk(),
        _tenant(),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("contact_info", sa.Text(), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
    )
    op.create_index("ix_franchisees_tenant", "franchisees", ["tenant_id"])
    op.create_index(
        "uq_franchisees_active_name",
        "franchisees",
        ["tenant_id", sa.text("lower(name)")],
        unique=True,
        postgresql_where=sa.text("archived_at IS NULL"),
    )

    op.create_table(
        "franchisee_groups",
        _uuid_pk(),
        _tenant(),
        sa.Column("name", sa.String(255), nullable=False),
        _created_at(),
    )
    op.create_index("ix_franchisee_groups_tenant", "franchisee_groups", ["tenant_id"])

    op.create_table(
        "franchisee_group_members",
        _uuid_pk(),
        _tenant(),
        sa.Column(
            "group_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("franchisee_groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "franchisee_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("franchisees.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.UniqueConstraint("group_id", "franchisee_id", name="uq_franchisee_group_members"),
    )
    op.create_index(
        "ix_franchisee_group_members_tenant", "franchisee_group_members", ["tenant_id"]
    )
    op.create_index(
        "ix_franchisee_group_members_group", "franchisee_group_members", ["group_id"]
    )
    op.create_index(
        "ix_franchisee_group_members_franchisee",
        "franchisee_group_members",
        ["franchisee_id"],
    )

    op.create_table(
        "stores",
        _uuid_pk(),
        _tenant(),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("code", sa.String(32), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column(
            "franchisee_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("franchisees.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
    )
    op.create_index("ix_stores_tenant", "stores", ["tenant_id"])
    op.create_index("ix_stores_franchisee", "stores", ["franchisee_id"])
    op.create_index(
        "uq_stores_active_name",
        "stores",
        ["tenant_id", sa.text("lower(name)")],
        unique=True,
        postgresql_where=sa.text("archived_at IS NULL"),
    )

    op.create_table(
        "store_groups",
        _uuid_pk(),
        _tenant(),
        sa.Column("name", sa.String(255), nullable=False),
        _created_at(),
    )
    op.create_index("ix_store_groups_tenant", "store_groups", ["tenant_id"])

    op.create_table(
        "store_group_members",
        _uuid_pk(),
        _tenant(),
        sa.Column(
            "group_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("store_groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "store_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("stores.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.UniqueConstraint("group_id", "store_id", name="uq_store_group_members"),
    )
    op.create_index("ix_store_group_members_tenant", "store_group_members", ["tenant_id"])
    op.create_index("ix_store_group_members_group", "store_group_members", ["group_id"])
    op.create_index("ix_store_group_members_store", "store_group_members", ["store_id"])

    op.create_table(
        "departments",
        _uuid_pk(),
        _tenant(),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "parent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("departments.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        _created_at(),
    )
    op.create_index("ix_departments_tenant", "departments", ["tenant_id"])
    op.create_index("ix_departments_parent", "departments", ["parent_id"])

    # --- HR-профили ---------------------------------------------------------
    op.create_table(
        "employee_profiles",
        _uuid_pk(),
        _tenant(),
        sa.Column(
            "employee_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("shadow_users.employee_id", ondelete="SET NULL"),
            nullable=True,
            unique=True,
        ),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("phone", sa.String(32), nullable=True),
        sa.Column(
            "position_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("positions.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "store_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("stores.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "department_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("departments.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "franchisee_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("franchisees.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "manager_profile_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("employee_profiles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("org_role", sa.String(32), nullable=False, server_default=sa.text("'employee'")),
        sa.Column("content_role", sa.String(32), nullable=False, server_default=sa.text("'none'")),
        sa.Column("hired_at", sa.Date(), nullable=True),
        sa.Column("status_text", sa.String(160), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'active'")),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archive_reason", sa.String(32), nullable=True),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("shadow_users.employee_id", ondelete="SET NULL"),
            nullable=True,
        ),
        _created_at(),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "org_role IN ('employee', 'tu', 'franchisee_owner', 'office')",
            name="ck_employee_profiles_org_role",
        ),
        sa.CheckConstraint(
            "content_role IN ('none', 'author', 'publisher')",
            name="ck_employee_profiles_content_role",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'archived')", name="ck_employee_profiles_status"
        ),
        sa.CheckConstraint(
            "archive_reason IS NULL OR "
            "archive_reason IN ('manual', 'auto_inactivity', 'auth_deleted')",
            name="ck_employee_profiles_archive_reason",
        ),
    )
    op.create_index("ix_employee_profiles_tenant", "employee_profiles", ["tenant_id"])
    op.create_index("ix_employee_profiles_status", "employee_profiles", ["status"])
    op.create_index("ix_employee_profiles_position", "employee_profiles", ["position_id"])
    op.create_index("ix_employee_profiles_store", "employee_profiles", ["store_id"])
    op.create_index("ix_employee_profiles_department", "employee_profiles", ["department_id"])
    op.create_index("ix_employee_profiles_franchisee", "employee_profiles", ["franchisee_id"])
    op.create_index("ix_employee_profiles_manager", "employee_profiles", ["manager_profile_id"])
    # Матчинг /api/me + защита от дублей: один активный профиль на email.
    op.create_index(
        "uq_employee_profiles_active_email",
        "employee_profiles",
        ["tenant_id", sa.text("lower(email)")],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "tu_store_assignments",
        sa.Column(
            "profile_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("employee_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "store_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("stores.id", ondelete="CASCADE"),
            nullable=False,
        ),
        _tenant(),
        _created_at(),
        sa.PrimaryKeyConstraint("profile_id", "store_id", name="pk_tu_store_assignments"),
    )
    op.create_index("ix_tu_store_assignments_tenant", "tu_store_assignments", ["tenant_id"])
    op.create_index("ix_tu_store_assignments_store", "tu_store_assignments", ["store_id"])

    # --- Пользовательские группы (после employee_profiles — FK на профили) --
    op.create_table(
        "user_groups",
        _uuid_pk(),
        _tenant(),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        _created_at(),
    )
    op.create_index("ix_user_groups_tenant", "user_groups", ["tenant_id"])

    op.create_table(
        "user_group_members",
        _uuid_pk(),
        _tenant(),
        sa.Column(
            "group_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "profile_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("employee_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "added_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("shadow_users.employee_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "added_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("group_id", "profile_id", name="uq_user_group_members"),
    )
    op.create_index("ix_user_group_members_tenant", "user_group_members", ["tenant_id"])
    op.create_index("ix_user_group_members_group", "user_group_members", ["group_id"])
    op.create_index("ix_user_group_members_profile", "user_group_members", ["profile_id"])

    # --- RLS ----------------------------------------------------------------
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY {table}_rls ON {table} USING ({RLS_POLICY})")


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f"DROP POLICY IF EXISTS {table}_rls ON {table}")
        op.drop_table(table)

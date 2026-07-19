"""HR-карточка сотрудника (Ф0 LMS) поверх shadow_users.

FK-инвариант домена learn: «действует человек (actor/author/owner) →
shadow_users.employee_id; данные О человеке (прогресс, назначения,
ознакомления, членства) → employee_profiles.id».

`employee_id` NULL, пока сотрудник ни разу не вошёл: HR заводит карточку
заранее, привязка происходит в /api/me матчингом по lower(email) — только
для principals с hub-ролью. Уникальность email среди активных — partial
unique index в миграции 0014 (uq_employee_profiles_active_email).

Архивация (увольнение/неактивность/удаление в auth) — через сервис
`archive_profile()` с полным каскадом; строки не удаляются, история
обучения сохраняется (ТЗ §23).
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

ORG_ROLES = ("employee", "tu", "franchisee_owner", "office")
CONTENT_ROLES = ("none", "author", "publisher")
PROFILE_STATUSES = ("active", "archived")
ARCHIVE_REASONS = ("manual", "auto_inactivity", "auth_deleted")


class EmployeeProfile(Base):
    __tablename__ = "employee_profiles"
    __table_args__ = (
        CheckConstraint(
            "org_role IN ('employee', 'tu', 'franchisee_owner', 'office')",
            name="ck_employee_profiles_org_role",
        ),
        CheckConstraint(
            "content_role IN ('none', 'author', 'publisher')",
            name="ck_employee_profiles_content_role",
        ),
        CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_employee_profiles_status",
        ),
        CheckConstraint(
            "archive_reason IS NULL OR "
            "archive_reason IN ('manual', 'auto_inactivity', 'auth_deleted')",
            name="ck_employee_profiles_archive_reason",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    # NULL до первого входа; уникальность — привязать два профиля к одному
    # аккаунту нельзя.
    employee_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("shadow_users.employee_id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)

    position_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("positions.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    store_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("stores.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    department_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("departments.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    # Только для org_role=franchisee_owner («чей это франчайзи-владелец»).
    # Франчайзи РЯДОВОГО сотрудника выводится из store.franchisee_id в
    # audience-резолвере — profile-поле протухало бы при переносе магазина.
    franchisee_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("franchisees.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    manager_profile_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("employee_profiles.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    org_role: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'employee'")
    )
    content_role: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'none'")
    )

    hired_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Строка-статус «как в мессенджерах» (ТЗ §16).
    status_text: Mapped[str | None] = mapped_column(String(160), nullable=True)

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'active'"), index=True
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archive_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Денормализация для правила «90 дней неактивности» (cron сверяет с
    # порогами из learning_settings).
    inactivity_warned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_activity_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("shadow_users.employee_id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        onupdate=text("now()"),
        nullable=False,
    )


class TuStoreAssignment(Base):
    """Закреплённые магазины территориального управляющего (ТЗ §2.1)."""

    __tablename__ = "tu_store_assignments"

    profile_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("employee_profiles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    store_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("stores.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

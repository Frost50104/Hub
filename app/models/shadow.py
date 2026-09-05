"""Shadow mirror of employees/tenants from signaris-auth.

`employee_id` / `id` come from the verified JWT — they're the canonical
identifiers used by all domain FKs.  `deleted_at` is required by the
deletion-sync worker (lib ≥ 0.4.0): we soft-delete rows on auth events and
filter `WHERE deleted_at IS NULL` at read time.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, String, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ShadowTenant(Base):
    __tablename__ = "shadow_tenants"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), server_default="active", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class ShadowUser(Base):
    __tablename__ = "shadow_users"

    employee_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), index=True, nullable=False
    )
    email: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Кеш штата из auth (0052, staff-sync): роль продукта и статус учётки.
    # client-lib'овский upsert эти колонки НЕ трогает (проверено: его SQL
    # обновляет ровно tenant_id/email/full_name/last_seen_at) — пишет только
    # pull-синк. NULL в auth_active = синка ещё не было.
    hub_role: Mapped[str | None] = mapped_column(String(16), nullable=True)
    auth_active: Mapped[bool | None] = mapped_column(nullable=True)
    staff_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AuthInvitation(Base):
    """Зеркало непринятого приглашения с ролью hub (0052, staff-sync).

    У приглашённого нет employee_id — в shadow_users ему места нет, а именно
    он отвечает админу на «добавлен, но ещё не входил». Снапшот: каждая
    синхронизация заменяет состав тенанта целиком (принятые/отозванные
    исчезают сами).
    """

    __tablename__ = "auth_invitations"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), index=True, nullable=False
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

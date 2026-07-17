"""Библиотека знаний (Ф1, ТЗ §8): разделы, материалы, версии, ознакомления.

Материал — файл (версии в material_versions, блоб на диске по storage_key)
или внешняя ссылка (kind=link, url). Доступ — через audience_id (NULL =
всем активным), фильтр списков — visible_filter().

Ack-семантика (из adversarial-ревью плана):
- подтверждение привязано к ВЕРСИИ, которую сервер отдал клиенту
  (version_no в запросе валидируется);
- re_ack_on_new_version=false → ack любой версии закрывает материал;
  true → требуется ack текущей версии;
- дедлайн — от max(published_at, granted_at члена аудитории);
- для kind=link версий нет — ack пишется с version_no=0.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import ContentLifecycleMixin

MATERIAL_KINDS = ("file", "link")


class LibrarySection(Base):
    __tablename__ = "library_sections"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    parent_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("library_sections.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    # Доступ на весь раздел (ТЗ §18: «разделы библиотеки»). NULL = всем.
    audience_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("audiences.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class LibraryMaterial(ContentLifecycleMixin, Base):
    __tablename__ = "library_materials"
    __table_args__ = (
        CheckConstraint("kind IN ('file', 'link')", name="ck_library_materials_kind"),
        CheckConstraint(
            "status IN ('draft', 'review', 'published', 'archived')",
            name="ck_library_materials_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    section_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("library_sections.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    audience_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("audiences.id", ondelete="SET NULL"),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    # Для kind=link: внешний URL (Google/Яндекс Диск и т.п., ТЗ §8).
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Номер актуальной версии файла (kind=file); NULL у link.
    current_version_no: Mapped[int | None] = mapped_column(Integer, nullable=True)

    requires_acknowledgement: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    re_ack_on_new_version: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    ack_deadline_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        onupdate=text("now()"),
        nullable=False,
    )


class MaterialVersion(Base):
    """Версия файла материала. Старые версии не удаляются (ТЗ §8.2)."""

    __tablename__ = "material_versions"
    __table_args__ = (
        UniqueConstraint("material_id", "version_no", name="uq_material_versions"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    material_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("library_materials.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    mime: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    uploaded_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("shadow_users.employee_id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class MaterialAcknowledgement(Base):
    """Факт «Ознакомлен» (ТЗ §8.1). version_no=0 — безверсионный (link)."""

    __tablename__ = "material_acknowledgements"

    material_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("library_materials.id", ondelete="CASCADE"),
        primary_key=True,
    )
    version_no: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("employee_profiles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    acknowledged_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class ViewHistory(Base):
    """Первое/последнее открытие объекта (гейт ack, «популярные», Ф2-история).

    Перенесена в Ф1 из плана Ф2: кнопка «Ознакомлен» гейтится фактом
    открытия документа (adversarial-ревью §24).
    """

    __tablename__ = "view_history"

    profile_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("employee_profiles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    object_type: Mapped[str] = mapped_column(String(32), primary_key=True)
    object_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    first_viewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    last_viewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    view_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))

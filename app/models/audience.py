"""Audience-движок (Ф0 LMS): правила видимости + материализованное членство.

Семантика (ТЗ §18):
- контентный объект несёт `audience_id NULL` = виден всем активным;
- внутри include-строки — AND непустых измерений («продавцы» И «группа
  магазинов X»);
- между include-строками — OR;
- exclude-строки вычитаются из результата include («…но не стажёры»);
- include-строка обязана иметь хотя бы одно непустое измерение (валидация
  на API — пустая строка означала бы «все» и открывала материал случайно);
- нет ни одной include-строки, но есть exclude → база «все активные» минус.

`audience_members` — материализованное членство: списки фильтруются одним
EXISTS без N+1. Пересчёт — `app/services/audience_resolver.py` под
advisory-locks; `granted_at` нужен ознакомлениям (дедлайн от момента
попадания в аудиторию, не от публикации) и хукам «вступил в аудиторию».

Измерения правил ссылаются на справочники ID-шниками в uuid[] — без FK
(массивы), консистентность чистится сервисом при удалении справочника.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

# Измерения audience-правил (колонки uuid[] в audience_rules).
RULE_DIMENSIONS = (
    "profile_ids",
    "position_ids",
    "position_group_ids",
    "store_ids",
    "store_group_ids",
    "franchisee_ids",
    "franchisee_group_ids",
    "department_ids",
    "user_group_ids",
)


class Audience(Base):
    __tablename__ = "audiences"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    # Явный шорткат «всем активным» — без строк-правил.
    is_all: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    # Отладочная подсказка, чем владеет audience («course:...», «material:...»).
    object_hint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        onupdate=text("now()"),
        nullable=False,
    )


class AudienceRule(Base):
    __tablename__ = "audience_rules"
    __table_args__ = (
        CheckConstraint("mode IN ('include', 'exclude')", name="ck_audience_rules_mode"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    audience_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("audiences.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    mode: Mapped[str] = mapped_column(String(8), nullable=False)

    profile_ids: Mapped[list[UUID] | None] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), nullable=True
    )
    position_ids: Mapped[list[UUID] | None] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), nullable=True
    )
    position_group_ids: Mapped[list[UUID] | None] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), nullable=True
    )
    store_ids: Mapped[list[UUID] | None] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), nullable=True
    )
    store_group_ids: Mapped[list[UUID] | None] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), nullable=True
    )
    franchisee_ids: Mapped[list[UUID] | None] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), nullable=True
    )
    franchisee_group_ids: Mapped[list[UUID] | None] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), nullable=True
    )
    department_ids: Mapped[list[UUID] | None] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), nullable=True
    )
    user_group_ids: Mapped[list[UUID] | None] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class AudienceMember(Base):
    __tablename__ = "audience_members"
    __table_args__ = (
        Index(
            "ix_audience_members_tenant_audience_profile",
            "tenant_id",
            "audience_id",
            "profile_id",
        ),
        Index("ix_audience_members_profile", "profile_id"),
    )

    audience_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("audiences.id", ondelete="CASCADE"),
        primary_key=True,
    )
    profile_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("employee_profiles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

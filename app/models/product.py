"""Ассортимент (Ф4, ТЗ §9): категории, карточки товаров, связи с обучением.

- ProductCard — ContentLifecycleMixin + audience (как материалы библиотеки):
  продавец видит только published-карточки своей аудитории.
- Фото — media_files (Ф3a): photos JSONB [{"media_id": "..."}]; отдача
  подписанными URL.
- ProductCardLink — «изучить по теме»: курс/урок/материал; названия
  резолвятся при отдаче (без FK — объект может жить в другом статусе).
- Первое открытие карточки сотрудником → activity-событие product.first_view.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import ContentLifecycleMixin

PRODUCT_LINK_TYPES = ("course", "lesson", "material")


class ProductCategory(Base):
    __tablename__ = "product_categories"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class ProductCard(ContentLifecycleMixin, Base):
    __tablename__ = "product_cards"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'review', 'published', 'archived')",
            name="ck_product_cards_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    category_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("product_categories.id", ondelete="SET NULL"),
        nullable=True,
    )
    audience_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("audiences.id", ondelete="SET NULL"),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # [{"media_id": "..."}] — подписанные URL добавляются при отдаче.
    photos: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    composition: Mapped[str | None] = mapped_column(Text, nullable=True)  # состав
    allergens: Mapped[str | None] = mapped_column(Text, nullable=True)
    shelf_life: Mapped[str | None] = mapped_column(Text, nullable=True)  # сроки/хранение
    serving: Mapped[str | None] = mapped_column(Text, nullable=True)  # подача/приготовление
    upsell: Mapped[str | None] = mapped_column(Text, nullable=True)  # допродажи
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        onupdate=text("now()"),
        nullable=False,
    )


class ProductCardLink(Base):
    __tablename__ = "product_card_links"
    __table_args__ = (
        CheckConstraint(
            "object_type IN ('course', 'lesson', 'material')",
            name="ck_product_card_links_type",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    product_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("product_cards.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    object_type: Mapped[str] = mapped_column(String(16), nullable=False)
    object_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

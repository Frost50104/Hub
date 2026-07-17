"""Избранное + аналитика поисковых запросов (Ф2, ТЗ §11/§10).

Полиморфные ссылки (object_type + object_id) без FK — осознанно: hard
delete разрешён только для черновиков, published-контент лишь архивируется,
поэтому orphan'ы почти невозможны; чистка — сервисно при delete.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

FAVORITE_TYPES = ("library_material", "news_post", "course", "product")


class Favorite(Base):
    __tablename__ = "favorites"

    profile_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("employee_profiles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    object_type: Mapped[str] = mapped_column(String(32), primary_key=True)
    object_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class SearchQueryLog(Base):
    """Что ищут сотрудники (ТЗ §10) — отчёты в Ф5, клики — тоже Ф5."""

    __tablename__ = "search_queries"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    profile_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("employee_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    query: Mapped[str] = mapped_column(String(512), nullable=False)
    results_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False, index=True
    )

"""Единый поисковый индекс learn-контента (Ф1) + очередь извлечения текста.

`search_documents` — одна строка на published-объект (материал, с Ф3 —
курс/урок/новость/товар). Черновики НЕ индексируются (заголовки не должны
светиться в выдаче). Наполняется ТОЛЬКО через
`app/services/search_indexer.py` (upsert при publish, delete при archive).

`search_vector` — STORED GENERATED tsvector (russian; title=A, snippet=B,
body=C) — создаётся raw SQL в миграции 0018, в ORM-модели не маппится
(читается только поисковыми запросами Ф5). `body_text` жёстко обрезается
сервисом (~200 KB) — лимиты tsvector.

Это же — источник «Новинок» (published_at DESC + audience-фильтр) и вход
для RAG (Ф6). `text_extraction_jobs` — каркас очереди (воркер — 2-я волна,
отдельный systemd-процесс: CPU-bound парсеры в uvicorn заморозят приложение).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class SearchDocument(Base):
    __tablename__ = "search_documents"
    __table_args__ = (
        UniqueConstraint("object_type", "object_id", name="uq_search_documents_object"),
        Index("ix_search_documents_tenant_published", "tenant_id", "published_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    object_type: Mapped[str] = mapped_column(String(32), nullable=False)
    object_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    audience_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("audiences.id", ondelete="SET NULL"),
        nullable=True,
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    # Готовый фронт-роут объекта («/learn/library?m=<id>») — выдача и «Новинки»
    # не собирают URL по object_type заново.
    url_path: Mapped[str] = mapped_column(String(512), nullable=False)
    # search_vector tsvector — генерируется в БД (0018), в ORM не маппится.


class TextExtractionJob(Base):
    __tablename__ = "text_extraction_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'done', 'failed')",
            name="ck_text_extraction_jobs_status",
        ),
        Index("ix_text_extraction_jobs_status", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    object_type: Mapped[str] = mapped_column(String(32), nullable=False)
    object_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    mime: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'pending'")
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        onupdate=text("now()"),
        nullable=False,
    )

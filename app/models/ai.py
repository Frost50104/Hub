"""AI-помощник (Ф6, ТЗ §19): RAG-чанки и диалоги.

- RagChunk строится ПОВЕРХ search_documents (published-контент, audience_id
  уже денормализован) — retrieval фильтрует по audience_members БЕЗ join
  на доменные таблицы (инвариант плана: ассистент не выдаёт содержимое
  чужих аудиторий).
- embedding — pgvector БЕЗ фиксированной размерности + embedding_model:
  смена LLM-провайдера (256/1024/1536-мерные векторы) не требует ALTER,
  retrieval сверяет модель, воркер переиндексирует устаревшие.
- ai_messages.sources — снапшот цитат (title+url) на момент ответа.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class RagChunk(Base):
    __tablename__ = "rag_chunks"
    __table_args__ = (
        UniqueConstraint(
            "object_type", "object_id", "chunk_index", name="uq_rag_chunks_object"
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    object_type: Mapped[str] = mapped_column(String(32), nullable=False)
    object_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    audience_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    url_path: Mapped[str] = mapped_column(String(512), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding = mapped_column(Vector(), nullable=False)  # размерность = у провайдера
    embedding_model: Mapped[str] = mapped_column(String(128), nullable=False)
    # updated_at источника (search_documents) — для reconcile-сверки.
    source_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class AiConversation(Base):
    __tablename__ = "ai_conversations"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    # Владелец диалога — СОТРУДНИК (FK-инвариант: «действует человек →
    # shadow_users»). Учебный профиль опционален: у пользователя-только-
    # трекера его нет, и раньше ассистент отвечал такому 404.
    employee_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("shadow_users.employee_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Нужен только retrieval'у базы знаний (фильтр по аудитории). NULL —
    # ассистент отвечает по трекеру, но не по учебным материалам.
    profile_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("employee_profiles.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        onupdate=text("now()"),
        nullable=False,
    )


class AiMessage(Base):
    """Оборот журнала операций.

    `role` в БД остаётся user|assistant — роль `tool` живёт только в памяти
    рантайма, история для модели пересобирается из kind+data.
    """

    __tablename__ = "ai_messages"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant')", name="ck_ai_messages_role"),
        CheckConstraint(
            "kind IN ('answer', 'summary', 'action', 'report', 'error', 'denied')",
            name="ck_ai_messages_kind",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    conversation_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("ai_conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    # Вид блока в журнале: answer|summary|action|report|error|denied.
    kind: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="answer", default="answer"
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    sources: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    # Тело блока: строки сводки, id плана, отчёт, кто вправе выполнить.
    data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class AiPlan(Base):
    """Предложенное действие, ожидающее подтверждения человеком.

    Порог (решение владельца): правки выполняются сразу, создание и архивация
    идут через план. Отмены у выполненного действия нет — правки делаются в
    трекере, — поэтому карточка плана единственная точка остановки.

    `args` — уже провалидированные аргументы инструмента: исполняется ИМЕННО
    поле, а не то, что пришлёт клиент в /execute. Права перепроверяются на
    исполнении, `expires_at` отсекает планы, пережившие свой контекст.
    """

    __tablename__ = "ai_plans"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'done', 'rejected', 'failed')",
            name="ck_ai_plans_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    conversation_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("ai_conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    message_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("ai_messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    employee_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("shadow_users.employee_id", ondelete="CASCADE"),
        nullable=False,
    )
    tool: Mapped[str] = mapped_column(String(64), nullable=False)
    args: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    preview: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="pending", default="pending"
    )
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    executed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

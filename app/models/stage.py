"""Этапы проекта — колонки доски с пользовательскими именами.

Этап — ЭТО ИМЯ КОЛОНКИ, и ничего больше (0044): «Идея», «Согласование»,
«Печать». Никакого системного смысла у колонки нет, состояние задачи живёт
отдельно — в `tasks.done` (выполнена или нет). До 0044 колонка была привязана
к одному из четырёх системных статусов, и доска не могла отойти от схемы
«к выполнению → в работе → на проверке → готово».

Единственное требование к проекту: **хотя бы одна колонка** — иначе новой
задаче некуда лечь (`tasks.stage_id` NOT NULL). Удаление последней → 409.

Позиции — непрерывные, UNIQUE(project_id, position) DEFERRABLE (как у секций):
колонки перетаскивают, и промежуточные дубли внутри транзакции допустимы.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ProjectStage(Base):
    __tablename__ = "project_stages"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "position",
            name="uq_project_stages_project_position",
            deferrable=True,
            initially="DEFERRED",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

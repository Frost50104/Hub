"""Этапы проекта — колонки доски с пользовательскими именами (редизайн 2026-08).

Этап привязан к одному из четырёх СИСТЕМНЫХ статусов (`system_status`):
«Проверка ТУ» — это этап статуса `in_review`, «Не разобрано» — `todo`.
`tasks.status` остаётся и всегда равен `stage.system_status` (зеркало): всё,
что читает статус — фильтры, stats, кроны due-soon/overdue, поиск, ассистент,
публичный просмотр — продолжает работать без правок. Единственная точка
записи обоих полей — `services/stages.py::set_stage`.

Позиции — непрерывные, UNIQUE(project_id, position) DEFERRABLE (как у секций):
колонки перетаскивают, и промежуточные дубли внутри транзакции допустимы.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
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

SYSTEM_STATUSES: tuple[str, ...] = ("todo", "in_progress", "in_review", "done")


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
        CheckConstraint(
            "system_status IN ('todo', 'in_progress', 'in_review', 'done')",
            name="ck_project_stages_system_status",
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
    system_status: Mapped[str] = mapped_column(String(16), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

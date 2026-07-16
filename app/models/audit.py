"""Журнал действий (ТЗ §27) — append-only.

Пишется сервисом `app/services/audit.py` из мутаций оргструктуры, доступов,
профилей и (с Ф1) из lifecycle-переходов контента. Read-API — hub:admin.

`object_label` — человекочитаемое имя на момент действия: переживает
удаление объекта. `diff` — только метаполя (старое/новое), НИКОГДА не
содержимое ответов опросов/попыток (ПДн).

RLS: только INSERT + SELECT (без UPDATE/DELETE-политик) — журнал не
редактируется даже приложением.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

AUDIT_ACTIONS = (
    "create",
    "update",
    "delete",
    "publish",
    "archive",
    "restore",
    "access_change",
    "import",
)


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_tenant_created", "tenant_id", "created_at"),
        Index("ix_audit_log_tenant_object", "tenant_id", "object_type", "object_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    actor_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("shadow_users.employee_id", ondelete="SET NULL"),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    object_type: Mapped[str] = mapped_column(String(32), nullable=False)
    object_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    object_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    diff: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

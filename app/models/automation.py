"""Автосценарии (Ф5, ТЗ §22): welcome-обучение без ручного назначения.

- AutomationRule: «профиль активирован / назначена должность из списка →
  назначить курс с дедлайном N дней». applies_from фиксирует момент
  создания правила: сканер применяет его ТОЛЬКО к профилям, созданным
  после — включение welcome-правила не накрывает 200 ветеранов
  (adversarial-ревью плана; CSV-импорт дополнительно защищён
  suppress_automations).
- AutomationJob: материализованное срабатывание (UNIQUE rule+profile —
  повторные прогоны сканера не дублируют). Правка правила НЕ ретро-меняет
  существующие jobs; архивация профиля отменяет pending.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

AUTOMATION_TRIGGERS = ("profile_activated", "position_assigned")
JOB_STATUSES = ("pending", "done", "cancelled")


class AutomationRule(Base):
    __tablename__ = "automation_rules"
    __table_args__ = (
        CheckConstraint(
            "trigger IN ('profile_activated', 'position_assigned')",
            name="ck_automation_rules_trigger",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    trigger: Mapped[str] = mapped_column(String(32), nullable=False)
    # position_assigned: пустой список = любая должность.
    position_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), nullable=False, server_default=text("'{}'")
    )
    course_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False,
    )
    due_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    # Профили, созданные ДО этого момента, правило не трогает.
    applies_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    created_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("shadow_users.employee_id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class AutomationJob(Base):
    __tablename__ = "automation_jobs"
    __table_args__ = (
        UniqueConstraint("rule_id", "profile_id", name="uq_automation_jobs_rule_profile"),
        CheckConstraint(
            "status IN ('pending', 'done', 'cancelled')", name="ck_automation_jobs_status"
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    rule_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("automation_rules.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    profile_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("employee_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    course_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'pending'")
    )
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

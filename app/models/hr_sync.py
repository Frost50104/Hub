"""Состояние синка кадровых данных из auth (0063, шаг 16d) — строка на тенант.

Заморозка кадровой правки в Hub читает ЭТУ строку, а не флаг потребителя:
выключатель `hr_consumer_enabled` останавливает обновления, но не открывает
правку тенанта, которым владеет auth. Разбор — `services/hr_state.py`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, DateTime, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class HrSyncState(Base):
    __tablename__ = "hr_sync_state"

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    # Из последнего ПОЛНОГО снимка справочников: неполный снимок, 403/404 и
    # сбой сети состояние не трогают — сбой не должен снимать заморозку.
    in_snapshot: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    authoritative: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    snapshot_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Ручное окно каткатa — пишет ТОЛЬКО CLI `app.jobs.hr_cutover`.
    cutover_freeze: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    cutover_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    applied_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_mode: Mapped[str | None] = mapped_column(String(16))
    last_report: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    pending_fingerprint: Mapped[str | None] = mapped_column(String(64))
    pending_ops: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    pending_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    blocked_reason: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

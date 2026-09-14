"""Персональные настройки интерфейса — одна строка на сотрудника.

Тема оформления принадлежит УЧЁТНОЙ ЗАПИСИ, а не браузеру: на общем устройстве
второй вошедший получал тему первого (localStorage переживает логаут). Ключ —
`shadow_users.employee_id`, как у `notification_preferences`: тень апсертится на
каждом аутентифицированном запросе (`app/deps.py`), поэтому строка доступна и
тем, у кого нет hub-роли и учебной карточки.

Таблица намеренно названа общо: следующая настройка интерфейса — колонка здесь,
а не третья таблица.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class UserPreference(Base):
    __tablename__ = "user_preferences"

    employee_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("shadow_users.employee_id", ondelete="CASCADE"),
        primary_key=True,
    )
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    # NULL и отсутствие DEFAULT обязательны: «строка есть, тему не выбирали» ≠
    # «выбрал тёмную». На различии стоит посев темы из localStorage при первом
    # входе после выката (web/src/lib/themeSync.ts) — с DEFAULT 'dark' он молча
    # записал бы тёмную всем подряд.
    theme: Mapped[str | None] = mapped_column(String(8), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        nullable=False,
    )

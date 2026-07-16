"""Запись в журнал действий (ТЗ §27).

`record()` добавляет строку в сессию БЕЗ commit — журнал попадает в ту же
транзакцию, что и само действие (нет действия без записи и наоборот).

`diff` — только метаполя вида {"field": {"old": ..., "new": ...}}. НИКОГДА
не класть содержимое ответов опросов/попыток тестов (ПДн).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog


def record(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    actor_id: UUID | None,
    action: str,
    object_type: str,
    object_id: UUID | None = None,
    object_label: str | None = None,
    diff: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditLog(
            tenant_id=tenant_id,
            actor_id=actor_id,
            action=action,
            object_type=object_type,
            object_id=object_id,
            object_label=(object_label or "")[:255] or None,
            diff=diff,
        )
    )


def field_diff(old: Any, new: Any, fields: list[str]) -> dict[str, Any]:
    """Diff по списку полей двух объектов/словарей (для record(diff=...))."""

    def _get(obj: Any, name: str) -> Any:
        value = obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)
        return str(value) if isinstance(value, UUID) else value

    out: dict[str, Any] = {}
    for name in fields:
        old_v, new_v = _get(old, name), _get(new, name)
        if old_v != new_v:
            out[name] = {"old": old_v, "new": new_v}
    return out

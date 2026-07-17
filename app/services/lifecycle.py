"""Lifecycle контента (ТЗ §25): draft → review → published → archived.

Единая точка переходов для всех контентных типов learn-домена (Ф1 —
материалы библиотеки; Ф2+ — новости/опросы/курсы). Побочные эффекты:
- publish: published_at=now, next_review_at из review_period_months;
- archive: archived_at=now;
- audit-запись в транзакции действия.

Поисковый индекс обновляет ВЫЗЫВАЮЩИЙ (payload типо-специфичен).

Guard: author — только draft→review своего черновика; publisher/admin — все
переходы. Hard delete разрешён только для draft (сервис контента проверяет
published_at IS NULL — «никогда не публиковался»).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from fastapi import HTTPException, status

from app.services import audit

ContentRole = Literal["admin", "publisher", "author", "none"]

_ALLOWED: dict[tuple[str, str], str] = {
    # (from, to) -> минимальная роль
    ("draft", "review"): "author",
    ("review", "draft"): "publisher",
    ("draft", "published"): "publisher",
    ("review", "published"): "publisher",
    ("published", "archived"): "publisher",
    ("archived", "published"): "publisher",
    ("archived", "draft"): "publisher",
}

_ROLE_RANK = {"none": 0, "author": 1, "publisher": 2, "admin": 3}

_AUDIT_ACTION = {"published": "publish", "archived": "archive"}


def can(role: ContentRole, need: str) -> bool:
    return _ROLE_RANK[role] >= _ROLE_RANK[need]


def transition(
    db,  # noqa: ANN001 — AsyncSession, sync-использование (add без flush)
    obj,  # noqa: ANN001 — модель с ContentLifecycleMixin
    new_status: str,
    *,
    actor_id: UUID | None,
    role: ContentRole,
    tenant_id: UUID,
    object_type: str,
    object_label: str,
) -> None:
    """Перевести объект в new_status или бросить 403/422."""
    old = obj.status
    if old == new_status:
        return
    need = _ALLOWED.get((old, new_status))
    if need is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Переход {old} → {new_status} невозможен",
        )
    if not can(role, need):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Недостаточно прав для этого перехода",
        )

    now = datetime.now(UTC)
    obj.status = new_status
    if new_status == "published":
        obj.published_at = now
        obj.archived_at = None
        if obj.review_period_months:
            obj.next_review_at = now + timedelta(days=30 * obj.review_period_months)
    elif new_status == "archived":
        obj.archived_at = now

    audit.record(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action=_AUDIT_ACTION.get(new_status, "update"),
        object_type=object_type,
        object_id=obj.id,
        object_label=object_label,
        diff={"status": {"old": old, "new": new_status}},
    )

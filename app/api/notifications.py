"""In-app inbox + per-user preferences."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, status
from signaris_auth import Principal
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db, require_auth_any
from app.models.notification import Notification, NotificationPreferences
from app.schemas.notification import (
    KindPreference,
    NotificationResponse,
    PreferencesResponse,
    PreferencesUpdate,
    ReadStateResult,
    ReadStateUpdate,
    UnreadCount,
)
from app.services.notification_prefs import normalize_prefs

router = APIRouter(tags=["notifications"])


@router.get("/notifications", response_model=list[NotificationResponse])
async def list_notifications(
    unread_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    before_id: int | None = Query(default=None),
    principal: Principal = Depends(require_auth_any()),
    db: AsyncSession = Depends(get_db),
) -> list[NotificationResponse]:
    """Страница «Входящих»: новейшие первыми, keyset-курсор `before_id`.

    Порядок — по `id`, а не по `created_at`: курсор сравнивает `id`, и при
    сортировке по времени строка перекрывшейся транзакции (`created_at` —
    начало транзакции, `id` — момент INSERT; на проде 7 таких пар, 19.10)
    на границе страницы пропадала или дублировалась. Расхождение осей —
    секунды, глазом не видно; группы «Последние 7 дней / Раньше» клиент
    считает построчно по `created_at`, от порядка они не зависят. `has_more`
    ручка не отдаёт: клиент просит `limit = 51` и по 51-й строке узнаёт, что
    следующая страница есть (`web/src/lib/inboxPaging.ts`).
    """
    stmt = (
        select(Notification)
        .where(Notification.employee_id == principal.employee_id)
        .order_by(Notification.id.desc())
        .limit(limit)
    )
    if unread_only:
        stmt = stmt.where(Notification.is_read.is_(False))
    if before_id is not None:
        stmt = stmt.where(Notification.id < before_id)
    rows = (await db.execute(stmt)).scalars().all()
    return [NotificationResponse.model_validate(n) for n in rows]


@router.get("/notifications/unread-count", response_model=UnreadCount)
async def unread_count(
    principal: Principal = Depends(require_auth_any()),
    db: AsyncSession = Depends(get_db),
) -> UnreadCount:
    row = await db.execute(
        select(func.count(Notification.id)).where(
            Notification.employee_id == principal.employee_id,
            Notification.is_read.is_(False),
        )
    )
    return UnreadCount(count=int(row.scalar_one()))


@router.post("/notifications/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_read(
    notification_id: int,
    principal: Principal = Depends(require_auth_any()),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Идемпотентно: нет строки — отвечать нечего, 204 без действий.

    Строку могло убрать удаление комментария или задачи, пока у человека были
    открыты «Входящие»; 404 здесь превращался в тост «Не удалось отметить
    прочитанным» поверх уже случившегося перехода в задачу. Чужой id получает
    тот же 204 и ничего не узнаёт.
    """
    n = await db.get(Notification, notification_id)
    if n is None or n.employee_id != principal.employee_id:
        return
    if not n.is_read:
        n.is_read = True
        n.read_at = datetime.now(UTC)
        await db.commit()


@router.post("/notifications/read-all", status_code=status.HTTP_204_NO_CONTENT)
async def mark_all_read(
    principal: Principal = Depends(require_auth_any()),
    db: AsyncSession = Depends(get_db),
) -> None:
    await db.execute(
        update(Notification)
        .where(
            Notification.employee_id == principal.employee_id,
            Notification.is_read.is_(False),
        )
        .values(is_read=True, read_at=datetime.now(UTC))
    )
    await db.commit()


@router.post("/notifications/read-state", response_model=ReadStateResult)
async def set_read_state(
    body: ReadStateUpdate,
    principal: Principal = Depends(require_auth_any()),
    db: AsyncSession = Depends(get_db),
) -> ReadStateResult:
    """Массово «прочитано»/«непрочитано» для выбранных во «Входящих» (19.10).

    Правила те же, что у `mark_read`: чужие и уже исчезнувшие id молча
    пропускаются (`employee_id` в WHERE), считаются только реально
    изменённые строки, повтор даёт 0. `read_at` при «непрочитано»
    сбрасывается в NULL: состояние хранится дважды, и рассинхрон ломал бы
    фильтр «Непрочитанные» (`is_read`) и подпись времени прочтения.
    `synchronize_session=False` — строки в сессию не грузились, а `rowcount`
    под asyncpg и так берётся из command tag.
    """
    result = await db.execute(
        update(Notification)
        .where(
            Notification.employee_id == principal.employee_id,
            Notification.id.in_(set(body.ids)),
            Notification.is_read.is_(not body.is_read),
        )
        .values(
            is_read=body.is_read,
            read_at=datetime.now(UTC) if body.is_read else None,
        )
        .execution_options(synchronize_session=False)
    )
    await db.commit()
    return ReadStateResult(updated=int(result.rowcount or 0))


# ─── Preferences ────────────────────────────────────────────────────────────


@router.get("/notifications/preferences", response_model=PreferencesResponse)
async def get_preferences(
    principal: Principal = Depends(require_auth_any()),
    db: AsyncSession = Depends(get_db),
) -> PreferencesResponse:
    row = await db.execute(
        select(NotificationPreferences.prefs).where(
            NotificationPreferences.employee_id == principal.employee_id
        )
    )
    raw = row.scalar_one_or_none()
    return PreferencesResponse(
        prefs={k: KindPreference(**v) for k, v in normalize_prefs(raw).items()}
    )


@router.put("/notifications/preferences", response_model=PreferencesResponse)
async def put_preferences(
    body: PreferencesUpdate,
    principal: Principal = Depends(require_auth_any()),
    db: AsyncSession = Depends(get_db),
) -> PreferencesResponse:
    # Normalise on write so the JSONB row never contains legacy bool-shape.
    normalised = normalize_prefs(body.prefs)
    await db.execute(
        pg_insert(NotificationPreferences)
        .values(
            employee_id=principal.employee_id,
            tenant_id=principal.tenant_id,
            prefs=normalised,
        )
        .on_conflict_do_update(
            index_elements=["employee_id"],
            set_={"prefs": normalised, "updated_at": datetime.now(UTC)},
        )
    )
    await db.commit()
    return PreferencesResponse(prefs={k: KindPreference(**v) for k, v in normalised.items()})

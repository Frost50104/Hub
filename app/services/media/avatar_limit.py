"""Месячный лимит минут гуся и резерв заказа. Резерв списывается при
постановке `compose`/`avatar_test` (`params.estimated_seconds`), по факту —
`result.billed_seconds`; отклонение модерацией возвращает минуты
(`billed_seconds=0`). Проверка и запись — под advisory-lock тенанта, иначе два
одновременных заказа проскочили бы через один и тот же остаток."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.learn_settings import get_settings_dict
from app.services.media import jobs
from app.services.media.hedra.pricing import cap_allows, month_bounds
from app.services.timefmt import display_tz


class AvatarLimitExceeded(Exception):
    def __init__(self, *, cap_minutes: int, used_seconds: float, need_seconds: float) -> None:
        self.cap_minutes = cap_minutes
        self.used_seconds = used_seconds
        self.need_seconds = need_seconds
        super().__init__(
            f"Лимит минут гуся на месяц исчерпан: занято {used_seconds / 60:.1f} из {cap_minutes}, "
            f"нужно ещё {need_seconds / 60:.1f}"
        )


async def lock_tenant(db: AsyncSession, tenant_id: UUID) -> None:
    await db.execute(select(func.pg_advisory_xact_lock(func.hashtext(f"media_avatar:{tenant_id}"))))


async def month_usage(
    db: AsyncSession, tenant_id: UUID, *, now: datetime | None = None
) -> tuple[int, float]:
    """(лимит в минутах, занято секунд с начала месяца в display tz)."""
    settings = await get_settings_dict(db, tenant_id)
    cap = int(settings.get("media_avatar_monthly_minutes_cap", 30))
    start, _nxt = month_bounds(now or datetime.now(display_tz()), display_tz())
    used = await jobs.monthly_avatar_seconds(db, month_start=start)
    return cap, used


async def reserve(db: AsyncSession, tenant_id: UUID, *, need_seconds: float) -> tuple[int, float]:
    """Проверить остаток под замком. Вызывающий ставит задание в ТОЙ ЖЕ
    транзакции — резерв виден следующему заказу сразу после commit."""
    await lock_tenant(db, tenant_id)
    cap, used = await month_usage(db, tenant_id)
    if not cap_allows(cap_minutes=cap, used_seconds=used, need_seconds=need_seconds):
        raise AvatarLimitExceeded(cap_minutes=cap, used_seconds=used, need_seconds=need_seconds)
    return cap, used

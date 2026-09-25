"""GET /api/env — public bootstrap config for the SPA.

The frontend reads version (for UpdateBanner), vapid_public_key (for push
subscribe) and sentry_dsn (for Sentry init) from this endpoint. Anonymous
access — no auth.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from app.config import get_settings
from app.db import tenant_scoped_session
from app.models.hr_sync import HrSyncState
from app.models.shadow import ShadowTenant
from app.services import hr_state
from app.services.push_sender import vapid_status

router = APIRouter(tags=["env"])


class EnvResponse(BaseModel):
    version: str
    environment: str
    vapid_public_key: str | None
    sentry_dsn: str | None
    # Таймзона, в которой срок задачи = календарный день (services/taskdates);
    # фронт считает «сегодня/просрочено» в ней же (lib/taskDates.setDisplayTz).
    display_timezone: str = "Europe/Moscow"


@router.get("/env", response_model=EnvResponse)
async def get_env() -> EnvResponse:
    settings = get_settings()
    return EnvResponse(
        version=settings.app_version,
        environment=settings.environment,
        vapid_public_key=settings.vapid_public_key,
        sentry_dsn=settings.sentry_dsn,
        display_timezone=settings.display_timezone,
    )


class PushHealthResponse(BaseModel):
    """Состояние транспорта уведомлений — без секретов и без чисел.

    Числа подписок здесь быть НЕ МОЖЕТ: ручка анонимная, `app.tenant_id` не
    выставлен, и RLS на `push_subscriptions` честно вернёт пусто — «0 подписок»
    читалось бы как «никто не подписан». Счётчики отдаёт `POST /api/push/test`,
    где есть тенант.
    """

    vapid: str


@router.get("/health/push", response_model=PushHealthResponse)
async def push_health() -> PushHealthResponse:
    """`ok` | `absent` | `invalid` | `mismatch`.

    Дёргается `scripts/healthcheck.sh` каждые 5 минут: web push однажды уже
    молча не работал месяц, потому что о поломке транспорта никто не узнавал.
    """
    return PushHealthResponse(vapid=vapid_status())


class HrHealthResponse(BaseModel):
    """Кадровые данные из auth (16d) — есть ли что чинить. Только коды:
    ручка анонимная, названий организаций и чисел здесь быть не должно."""

    status: str  # ok | attention
    problems: list[str]


@router.get("/health/hr", response_model=HrHealthResponse)
async def hr_health() -> HrHealthResponse:
    """`scripts/healthcheck.sh` шлёт алерт при смене набора проблем.

    Коды — `hr_state.health_problems`: забытое окно каткатa, изменения, которые
    больше часа ждут hub-admin, организация заморожена без применения, давно не
    было успешного применения. Каждое из этого — «правка кадров в Hub закрыта,
    а из auth ничего не приходит», и узнавать об этом надо не по жалобе.
    """
    settings = get_settings()
    now = datetime.now(UTC)
    problems: set[str] = set()
    async with tenant_scoped_session(None, bypass_rls=True) as db:
        slugs = dict((await db.execute(select(ShadowTenant.id, ShadowTenant.slug))).tuples().all())
        for row in (await db.execute(select(HrSyncState))).scalars():
            applying = hr_state.tenant_applies(
                slugs.get(row.tenant_id), settings.hr_apply_tenant_slugs
            )
            problems.update(hr_state.health_problems(row, applying=applying, now=now))
    return HrHealthResponse(status="attention" if problems else "ok", problems=sorted(problems))

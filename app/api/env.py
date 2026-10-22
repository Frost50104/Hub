"""GET /api/env — public bootstrap config for the SPA.

The frontend reads version (Sentry release; the update banner compares
`/version.json` instead), vapid_public_key (for push
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
from app.models.race import RaceContest, RaceSyncState
from app.models.shadow import ShadowTenant
from app.services import hr_state
from app.services.iiko import service as iiko_service
from app.services.media import gate as media_gate
from app.services.media import health as media_health
from app.services.push_sender import vapid_status
from app.services.race import gate as race_gate
from app.services.race import health as race_health
from app.services.race.baselines import preliminary_scopes
from app.services.timefmt import display_tz

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


class RaceHealthResponse(BaseModel):
    """«Гусиная гонка» — выгрузка iiko, ночное закрытие, активация, базы.
    Только коды: ручка анонимная, названий тенантов, чисел и текста ошибок
    iiko здесь нет."""

    status: str  # ok | attention | disabled
    problems: list[str]
    checked_at: datetime


@router.get("/health/race", response_model=RaceHealthResponse)
async def race_health_view() -> RaceHealthResponse:
    """`scripts/healthcheck.sh` шлёт алерт при смене набора проблем.

    `disabled` — обращения к iiko выключены (`SIGNARIS_HUB_RACE_SYNC_ENABLED`,
    staging) или iiko не настроен: проверять нечего. Иначе — коды
    `race_health.health_problems` по каждому тенанту с конкурсом
    `scheduled|active` и включённым тумблером.
    """
    now = datetime.now(UTC)
    if not race_gate.sync_enabled() or not iiko_service.is_configured():
        return RaceHealthResponse(status="disabled", problems=[], checked_at=now)
    tz = display_tz()
    problems: set[str] = set()
    async with tenant_scoped_session(None, bypass_rls=True) as db:
        contests = list(
            (
                await db.execute(
                    select(RaceContest).where(RaceContest.status.in_(("scheduled", "active")))
                )
            ).scalars()
        )
        by_tenant: dict = {}
        for c in contests:
            cur = by_tenant.get(c.tenant_id)
            # активный важнее запланированного; из запланированных — ближайший
            if cur is None or (c.status == "active") > (cur.status == "active") or (
                c.status == cur.status and c.starts_on < cur.starts_on
            ):
                by_tenant[c.tenant_id] = c
        for tenant_id, c in by_tenant.items():
            if not await race_gate.tenant_enabled(db, tenant_id):
                continue
            state = await db.get(RaceSyncState, tenant_id)
            last_close_day = None if state is None else state.last_close_day
            preliminary = 0
            if last_close_day is not None:
                preliminary = len(
                    await preliminary_scopes(db, c.id, through_day=last_close_day, tz=tz)
                )
            snapshot = race_health.TenantRaceHealth(
                contest_status=c.status,
                contest_starts_on=c.starts_on,
                scheduled_at=c.scheduled_at,
                last_success_at=None if state is None else state.last_success_at,
                last_error=None if state is None else state.last_error,
                last_close_day=last_close_day,
                preliminary_closed=preliminary,
            )
            problems.update(race_health.health_problems(snapshot, now=now, tz=tz))
    return RaceHealthResponse(
        status="attention" if problems else "ok", problems=sorted(problems), checked_at=now
    )


class MediaHealthResponse(BaseModel):
    """Конвейер видео урока (0066): воркер, очередь, конфигурация расшифровки
    и гуся. Только коды: ручка анонимная."""

    status: str  # ok | attention | disabled
    problems: list[str]
    checked_at: datetime


@router.get("/health/media", response_model=MediaHealthResponse)
async def media_health_view() -> MediaHealthResponse:
    """`scripts/healthcheck.sh` шлёт алерт при смене набора проблем.

    `disabled` — env-рубильник `SIGNARIS_HUB_MEDIA_PIPELINE_ENABLED` выключен
    (прод до go-live): проверять нечего. Иначе — коды
    `media_health.health_problems` по снимку очереди под bypass.
    """
    now = datetime.now(UTC)
    if not media_gate.env_enabled():
        return MediaHealthResponse(status="disabled", problems=[], checked_at=now)
    async with tenant_scoped_session(None, bypass_rls=True) as db:
        snapshot = await media_health.collect_snapshot(db, settings=get_settings(), now=now)
    problems = media_health.health_problems(snapshot, now=now)
    return MediaHealthResponse(
        status="attention" if problems else "ok", problems=problems, checked_at=now
    )

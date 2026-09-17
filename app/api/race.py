"""«Гусиная гонка» (0057): экран сотрудника, админка, настройки.

Гейты:
- пользовательские ручки — любой с hub-ролью, но при выключенном модуле 404
  («как будто её и не было»); трек видят все — прозрачность рейтинга по ТЗ;
- админские — hub-admin; при выключенном тенантном тумблере 409, кроме
  `settings` (иначе включить неоткуда); при выключенном env-флаге 404 всё.
Ошибки правил → 422/409 русским текстом; iiko: Busy 409, ошибка 502, не
настроено 503, выгрузка выключена на окружении 409.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from signaris_auth import Principal
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import enforce_rate_limit, get_db, require_auth
from app.models.org import Store
from app.models.race import Race, RaceContest, RaceSyncState
from app.models.shadow import ShadowUser
from app.schemas.race import (
    AdminParticipantOut,
    BaselineOut,
    BaselinePut,
    BaselineRecompute,
    BaselineReportOut,
    ChartResponse,
    ContestAdminOut,
    ContestCreate,
    ContestOut,
    ContestUpdate,
    FinishOut,
    HistoryResponse,
    ParticipantToggle,
    ParticipantToggleOut,
    RaceResultsResponse,
    RaceSettingsOut,
    RaceSettingsPut,
    ScheduleOut,
    StoreRefOut,
    SyncReportOut,
    SyncRequest,
    SyncStateOut,
    TrackResponse,
    TvLinkOut,
)
from app.services import audit
from app.services.iiko.client import IikoError, IikoNotConfigured
from app.services.iiko.service import IikoBusy
from app.services.org_scope import get_profile
from app.services.race import engine, gate, iiko_pull, read, tv_token
from app.services.race.baselines import load_baselines

router = APIRouter(tags=["race"])

_ADMIN = require_auth(roles=["admin"])
_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Не найдено")
_OFF = HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Гусиная гонка выключена")


# ─── гейты и общие помощники ────────────────────────────────────────────────


async def _require_user_access(db: AsyncSession, principal: Principal) -> None:
    if not await gate.race_enabled_for(db, principal.tenant_id):
        raise _NOT_FOUND


async def _require_admin_access(db: AsyncSession, principal: Principal) -> None:
    if not gate.env_enabled():
        raise _NOT_FOUND
    if not await gate.tenant_enabled(db, principal.tenant_id):
        raise _OFF


async def _load_contest(db: AsyncSession, contest_id: UUID) -> RaceContest:
    contest = await db.get(RaceContest, contest_id)
    if contest is None:
        raise HTTPException(status_code=404, detail="Конкурс не найден")
    return contest


async def _load_race(db: AsyncSession, race_id: UUID) -> tuple[RaceContest, Race]:
    race = await db.get(Race, race_id)
    if race is None:
        raise HTTPException(status_code=404, detail="Заезд не найден")
    return await _load_contest(db, race.contest_id), race


async def _my_store_id(db: AsyncSession, principal: Principal) -> UUID | None:
    profile = await get_profile(db, principal)
    return profile.store_id if profile is not None else None


def _http(e: Exception) -> HTTPException:
    if isinstance(e, engine.RaceValidationError):
        return HTTPException(status_code=422, detail=str(e))
    if isinstance(e, engine.RaceConflictError):
        return HTTPException(status_code=409, detail=str(e))
    if isinstance(e, iiko_pull.RaceSyncDisabled):
        return HTTPException(status_code=409, detail=str(e))
    if isinstance(e, IikoNotConfigured):
        return HTTPException(status_code=503, detail=str(e))
    if isinstance(e, IikoBusy):
        return HTTPException(status_code=409, detail=str(e))
    if isinstance(e, IikoError):
        return HTTPException(status_code=502, detail=str(e))
    raise e


async def _lock_timeout(db: AsyncSession) -> None:
    # Админ не должен висеть на advisory-локе ночной джобы без потолка.
    await db.execute(text("SET LOCAL lock_timeout = '5s'"))


# ─── сотрудник ──────────────────────────────────────────────────────────────


@router.get("/learn/race", response_model=TrackResponse)
async def get_track(
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> TrackResponse:
    await _require_user_access(db, principal)
    contest = await read.current_contest(db, principal.tenant_id)
    payload = await read.build_track(
        db,
        contest,
        today=engine.today_local(),
        my_store_id=await _my_store_id(db, principal),
        tenant_id=principal.tenant_id,
    )
    return TrackResponse(**payload)


@router.get("/learn/race/races/{race_id}", response_model=RaceResultsResponse)
async def get_race_results(
    race_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> RaceResultsResponse:
    await _require_user_access(db, principal)
    contest, race = await _load_race(db, race_id)
    return RaceResultsResponse(
        **await read.race_results_view(db, contest, race, today=engine.today_local())
    )


@router.get("/learn/race/history", response_model=HistoryResponse)
async def get_history(
    store_id: Annotated[UUID | None, Query()] = None,
    contest_id: Annotated[UUID | None, Query()] = None,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> HistoryResponse:
    await _require_user_access(db, principal)
    target = store_id or await _my_store_id(db, principal)
    if target is None:
        raise HTTPException(status_code=422, detail="Укажите точку")
    contest = (
        await _load_contest(db, contest_id)
        if contest_id is not None
        else await read.current_contest(db, principal.tenant_id)
    )
    if contest is None:
        raise HTTPException(status_code=404, detail="Конкурс ещё не объявлен")
    return HistoryResponse(
        contest_id=contest.id,
        store_id=target,
        races=await read.store_history(db, contest, target),
    )


@router.get("/learn/race/races/{race_id}/chart", response_model=ChartResponse)
async def get_chart(
    race_id: UUID,
    store_id: Annotated[UUID | None, Query()] = None,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> ChartResponse:
    await _require_user_access(db, principal)
    target = store_id or await _my_store_id(db, principal)
    if target is None:
        raise HTTPException(status_code=422, detail="Укажите точку")
    contest, race = await _load_race(db, race_id)
    return ChartResponse(
        **await read.race_chart(db, contest, race, target, today=engine.today_local())
    )


# ─── настройки (тумблер живёт всегда) ───────────────────────────────────────


@router.get("/learn/race/admin/settings", response_model=RaceSettingsOut)
async def get_settings_endpoint(
    principal: Principal = Depends(_ADMIN),
    db: AsyncSession = Depends(get_db),
) -> RaceSettingsOut:
    if not gate.env_enabled():
        raise _NOT_FOUND
    return RaceSettingsOut(
        enabled=await gate.tenant_enabled(db, principal.tenant_id),
        env_enabled=True,
        sync_enabled=gate.sync_enabled(),
    )


@router.put("/learn/race/admin/settings", response_model=RaceSettingsOut)
async def put_settings(
    body: RaceSettingsPut,
    principal: Principal = Depends(_ADMIN),
    db: AsyncSession = Depends(get_db),
) -> RaceSettingsOut:
    if not gate.env_enabled():
        raise _NOT_FOUND
    old = await gate.tenant_enabled(db, principal.tenant_id)
    if old != body.enabled:
        await gate.set_tenant_enabled(db, principal.tenant_id, body.enabled)
        audit.record(
            db,
            tenant_id=principal.tenant_id,
            actor_id=principal.employee_id,
            action="update",
            object_type="race_settings",
            object_label="Гусиная гонка",
            diff={"enabled": {"old": old, "new": body.enabled}},
        )
        await db.commit()
    return RaceSettingsOut(enabled=body.enabled, env_enabled=True, sync_enabled=gate.sync_enabled())


# ─── админ: конкурсы ────────────────────────────────────────────────────────


async def _contest_out(db: AsyncSession, contest: RaceContest) -> ContestOut:
    return ContestOut(
        **read.contest_dict(
            contest, await read.load_leagues(db, contest), await read.load_races(db, contest)
        )
    )


async def _admin_participants(
    db: AsyncSession, contest: RaceContest
) -> tuple[list[AdminParticipantOut], list[StoreRefOut]]:
    rows = await read.load_participants(db, contest, include_excluded=True)
    by_dept: dict[str, list[UUID]] = {}
    for p in rows:
        by_dept.setdefault(p.department_id, []).append(p.store_id)
    out = [
        AdminParticipantOut(
            store_id=p.store_id,
            name=p.name,
            code=p.code,
            department_id=p.department_id,
            league_id=p.league_id,
            included=p.excluded_at is None,
            exclude_reason=p.exclude_reason,
            department_shared_with=[s for s in by_dept[p.department_id] if s != p.store_id],
        )
        for p in rows
    ]
    known = {p.store_id for p in rows}
    stores = list(
        (
            await db.execute(
                select(Store.id, Store.name, Store.code)
                .where(Store.archived_at.is_(None))
                .order_by(Store.name)
            )
        ).all()
    )
    depts = await engine.department_ids_by_store(db, contest.tenant_id, [s[0] for s in stores])
    unlinked = [
        StoreRefOut(store_id=sid, name=name, code=code)
        for sid, name, code in stores
        if sid not in known and sid not in depts
    ]
    return out, unlinked


async def _admin_detail(db: AsyncSession, contest: RaceContest) -> ContestAdminOut:
    participants, unlinked = await _admin_participants(db, contest)
    state = await db.get(RaceSyncState, contest.tenant_id)
    return ContestAdminOut(
        contest=await _contest_out(db, contest),
        participants=participants,
        unlinked_stores=unlinked,
        sync=SyncStateOut.model_validate(state, from_attributes=True)
        if state is not None
        else SyncStateOut(),
        tv_links=[_tv_out(t) for t in await tv_token.list_tv_tokens(db, contest.tenant_id)],
        sync_enabled=gate.sync_enabled(),
    )


def _tv_out(row: Any) -> TvLinkOut:
    return TvLinkOut(
        id=row.id,
        token=row.token,
        url=tv_token.build_tv_url(row.token),
        created_at=row.created_at,
        revoked_at=row.revoked_at,
    )


@router.get("/learn/race/admin/contests", response_model=list[ContestOut])
async def list_contests(
    principal: Principal = Depends(_ADMIN),
    db: AsyncSession = Depends(get_db),
) -> list[ContestOut]:
    await _require_admin_access(db, principal)
    rows = list(
        (
            await db.execute(
                select(RaceContest)
                .where(RaceContest.tenant_id == principal.tenant_id)
                .order_by(RaceContest.starts_on.desc(), RaceContest.created_at.desc())
            )
        ).scalars()
    )
    return [await _contest_out(db, c) for c in rows]


@router.post("/learn/race/admin/contests", response_model=ContestAdminOut, status_code=201)
async def create_contest(
    body: ContestCreate,
    principal: Principal = Depends(_ADMIN),
    db: AsyncSession = Depends(get_db),
) -> ContestAdminOut:
    await _require_admin_access(db, principal)
    try:
        contest = await engine.create_contest(
            db,
            tenant_id=principal.tenant_id,
            actor_id=principal.employee_id,
            title=body.title,
            starts_on=body.starts_on,
            race_length_days=body.race_length_days,
            weeks_total=body.weeks_total,
            baseline_mode=body.baseline_mode,
            baseline_days=body.baseline_days,
            league_group_ids=body.league_group_ids,
        )
    except (engine.RaceValidationError, engine.RaceConflictError) as e:
        raise _http(e) from None
    await db.commit()
    return await _admin_detail(db, contest)


@router.get("/learn/race/admin/contests/{contest_id}", response_model=ContestAdminOut)
async def get_contest_admin(
    contest_id: UUID,
    principal: Principal = Depends(_ADMIN),
    db: AsyncSession = Depends(get_db),
) -> ContestAdminOut:
    await _require_admin_access(db, principal)
    return await _admin_detail(db, await _load_contest(db, contest_id))


@router.patch("/learn/race/admin/contests/{contest_id}", response_model=ContestAdminOut)
async def patch_contest(
    contest_id: UUID,
    body: ContestUpdate,
    principal: Principal = Depends(_ADMIN),
    db: AsyncSession = Depends(get_db),
) -> ContestAdminOut:
    await _require_admin_access(db, principal)
    contest = await _load_contest(db, contest_id)
    try:
        await engine.update_contest(
            db,
            contest,
            actor_id=principal.employee_id,
            **body.model_dump(exclude_unset=True),
        )
    except (engine.RaceValidationError, engine.RaceConflictError) as e:
        raise _http(e) from None
    await db.commit()
    return await _admin_detail(db, contest)


@router.post("/learn/race/admin/contests/{contest_id}/schedule", response_model=ScheduleOut)
async def schedule_contest(
    contest_id: UUID,
    principal: Principal = Depends(_ADMIN),
    db: AsyncSession = Depends(get_db),
) -> ScheduleOut:
    await _require_admin_access(db, principal)
    contest = await _load_contest(db, contest_id)
    await _lock_timeout(db)
    try:
        report = await engine.schedule(
            db,
            contest,
            today=engine.today_local(),
            actor_id=principal.employee_id,
            compute_baselines=iiko_pull.compute_baselines if gate.sync_enabled() else None,
        )
    except (
        engine.RaceValidationError,
        engine.RaceConflictError,
        iiko_pull.RaceSyncDisabled,
        IikoNotConfigured,
        IikoBusy,
        IikoError,
    ) as e:
        raise _http(e) from None
    await db.commit()
    return ScheduleOut(
        contest=await _contest_out(db, contest),
        races=report.races,
        needs_baseline_store_ids=report.needs_baseline_store_ids,
        baselines_computed=report.baselines_computed,
    )


@router.post("/learn/race/admin/contests/{contest_id}/cancel", response_model=ContestAdminOut)
async def cancel_contest(
    contest_id: UUID,
    principal: Principal = Depends(_ADMIN),
    db: AsyncSession = Depends(get_db),
) -> ContestAdminOut:
    await _require_admin_access(db, principal)
    contest = await _load_contest(db, contest_id)
    await _lock_timeout(db)
    try:
        await engine.cancel_contest(
            db, contest, today=engine.today_local(), actor_id=principal.employee_id
        )
    except engine.RaceConflictError as e:
        raise _http(e) from None
    await db.commit()
    return await _admin_detail(db, contest)


@router.post("/learn/race/admin/races/{race_id}/finish", response_model=FinishOut)
async def finish_race(
    race_id: UUID,
    principal: Principal = Depends(_ADMIN),
    db: AsyncSession = Depends(get_db),
) -> FinishOut:
    await _require_admin_access(db, principal)
    contest, race = await _load_race(db, race_id)
    await _lock_timeout(db)
    try:
        _results, pull_ok = await engine.force_finish(
            db,
            contest,
            race,
            today=engine.today_local(),
            actor_id=principal.employee_id,
            pull=iiko_pull.pull_days if gate.sync_enabled() else None,
        )
    except engine.RaceConflictError as e:
        raise _http(e) from None
    await db.commit()
    view = await read.race_results_view(db, contest, race, today=engine.today_local())
    return FinishOut(race=view["race"], results=view["results"], pull_ok=pull_ok)


# ─── админ: участники и база ────────────────────────────────────────────────


@router.put(
    "/learn/race/admin/contests/{contest_id}/participants/{store_id}",
    response_model=ParticipantToggleOut,
)
async def toggle_participant(
    contest_id: UUID,
    store_id: UUID,
    body: ParticipantToggle,
    principal: Principal = Depends(_ADMIN),
    db: AsyncSession = Depends(get_db),
) -> ParticipantToggleOut:
    await _require_admin_access(db, principal)
    contest = await _load_contest(db, contest_id)
    try:
        replaced = await engine.set_participant(
            db,
            contest,
            store_id=store_id,
            included=body.included,
            actor_id=principal.employee_id,
        )
    except (engine.RaceValidationError, engine.RaceConflictError) as e:
        raise _http(e) from None
    await db.commit()
    participants, _ = await _admin_participants(db, contest)
    return ParticipantToggleOut(participants=participants, replaced_store_id=replaced)


@router.post(
    "/learn/race/admin/contests/{contest_id}/participants/refresh",
    response_model=ContestAdminOut,
)
async def refresh_participants(
    contest_id: UUID,
    principal: Principal = Depends(_ADMIN),
    db: AsyncSession = Depends(get_db),
) -> ContestAdminOut:
    await _require_admin_access(db, principal)
    contest = await _load_contest(db, contest_id)
    if contest.status in ("finished", "cancelled"):
        raise HTTPException(status_code=409, detail="Конкурс завершён — состав изменить нельзя")
    await engine.materialize_participants(db, contest, actor_id=principal.employee_id)
    await db.commit()
    return await _admin_detail(db, contest)


async def _baselines_out(
    db: AsyncSession, contest: RaceContest, race_id: UUID | None
) -> list[BaselineOut]:
    participants = await read.load_participants(db, contest)
    baselines = await load_baselines(db, contest, race_id)
    setters = {b.set_by for b in baselines.values() if b.set_by is not None}
    names = {}
    if setters:
        names = dict(
            (
                await db.execute(
                    select(ShadowUser.employee_id, ShadowUser.full_name).where(
                        ShadowUser.employee_id.in_(setters)
                    )
                )
            ).all()
        )
    out: list[BaselineOut] = []
    for p in participants:
        b = baselines.get(p.store_id)
        out.append(
            BaselineOut(
                store_id=p.store_id,
                name=p.name,
                code=p.code,
                race_id=None if b is None else b.race_id,
                value=None if b is None else b.value,
                source=None if b is None else b.source,
                receipts=None if b is None else b.receipts,
                items=None if b is None else b.items,
                period_from=None if b is None else b.period_from,
                period_to=None if b is None else b.period_to,
                note=None if b is None else b.note,
                set_by=None if b is None else b.set_by,
                set_by_name=None if b is None or b.set_by is None else names.get(b.set_by),
                set_at=None if b is None else b.set_at,
                needs_baseline=b is None or b.value is None,
            )
        )
    return out


@router.get("/learn/race/admin/contests/{contest_id}/baselines", response_model=list[BaselineOut])
async def list_baselines(
    contest_id: UUID,
    race_id: Annotated[UUID | None, Query()] = None,
    principal: Principal = Depends(_ADMIN),
    db: AsyncSession = Depends(get_db),
) -> list[BaselineOut]:
    await _require_admin_access(db, principal)
    contest = await _load_contest(db, contest_id)
    return await _baselines_out(db, contest, race_id)


@router.put(
    "/learn/race/admin/contests/{contest_id}/baselines/{store_id}",
    response_model=list[BaselineOut],
)
async def put_baseline(
    contest_id: UUID,
    store_id: UUID,
    body: BaselinePut,
    principal: Principal = Depends(_ADMIN),
    db: AsyncSession = Depends(get_db),
) -> list[BaselineOut]:
    await _require_admin_access(db, principal)
    contest = await _load_contest(db, contest_id)
    try:
        await engine.set_baseline(
            db,
            contest,
            store_id=store_id,
            race_id=body.race_id,
            value=body.value,
            note=body.note,
            actor_id=principal.employee_id,
        )
    except engine.RaceValidationError as e:
        raise _http(e) from None
    await db.commit()
    return await _baselines_out(db, contest, body.race_id)


@router.post(
    "/learn/race/admin/contests/{contest_id}/baselines/recompute",
    response_model=BaselineReportOut,
)
async def recompute_baselines(
    contest_id: UUID,
    body: BaselineRecompute,
    principal: Principal = Depends(_ADMIN),
    db: AsyncSession = Depends(get_db),
) -> BaselineReportOut:
    await _require_admin_access(db, principal)
    contest = await _load_contest(db, contest_id)
    race = await db.get(Race, body.race_id) if body.race_id is not None else None
    if body.race_id is not None and (race is None or race.contest_id != contest.id):
        raise HTTPException(status_code=404, detail="Заезд не найден")
    await enforce_rate_limit(
        bucket="race:sync", employee_id=str(principal.employee_id), limit=3, window_sec=300
    )
    try:
        report = await iiko_pull.compute_baselines(
            db,
            contest=contest,
            race=race,
            force=body.force,
            pull=gate.sync_enabled(),
            set_by=principal.employee_id,
        )
    except (iiko_pull.RaceSyncDisabled, IikoNotConfigured, IikoBusy, IikoError) as e:
        raise _http(e) from None
    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor_id=principal.employee_id,
        action="update",
        object_type="race_contest",
        object_id=contest.id,
        object_label=f"{contest.title} · пересчёт базы",
        diff={"baselines_computed": {"old": None, "new": report.computed}},
    )
    await db.commit()
    return BaselineReportOut(**report.__dict__)


# ─── админ: выгрузка и ТВ-ссылки ────────────────────────────────────────────


@router.post("/learn/race/admin/sync", response_model=SyncReportOut)
async def manual_sync(
    body: SyncRequest | None = None,
    dry_run: bool = Query(default=False),
    principal: Principal = Depends(_ADMIN),
    db: AsyncSession = Depends(get_db),
) -> SyncReportOut:
    """«Обновить данные сейчас» и дотяжка пропущенных дней (окно ≤ 31 дня)."""
    await _require_admin_access(db, principal)
    if not gate.sync_enabled():
        raise HTTPException(
            status_code=409, detail="Выгрузка iiko для гонки на этом окружении выключена"
        )
    today = engine.today_local()
    day_to = (body.day_to if body else None) or today
    day_from = (body.day_from if body else None) or (day_to - timedelta(days=1))
    if day_to < day_from:
        raise HTTPException(status_code=422, detail="Конец окна раньше начала")
    if (day_to - day_from).days + 1 > iiko_pull.MAX_MANUAL_PULL_DAYS:
        raise HTTPException(
            status_code=422, detail=f"Окно не больше {iiko_pull.MAX_MANUAL_PULL_DAYS} дней"
        )
    await enforce_rate_limit(
        bucket="race:sync", employee_id=str(principal.employee_id), limit=3, window_sec=300
    )
    last: iiko_pull.PullReport | None = None
    rows = departments = days = 0
    written = True
    skipped = False
    try:
        for a, b in _windows(day_from, day_to):
            last = await iiko_pull.pull_days(
                db, tenant_id=principal.tenant_id, day_from=a, day_to=b, dry_run=dry_run
            )
            rows += last.rows
            departments = max(departments, last.departments)
            days += last.days
            written = written and last.written
            skipped = skipped or last.skipped_empty
    except (IikoNotConfigured, IikoBusy, IikoError) as e:
        await db.commit()  # запись об ошибке в race_sync_state
        raise _http(e) from None
    await db.commit()
    return SyncReportOut(
        dry_run=dry_run,
        day_from=day_from,
        day_to=day_to,
        rows=rows,
        departments=departments,
        days=days,
        written=written and not dry_run,
        skipped_empty=skipped,
    )


def _windows(day_from: date, day_to: date) -> list[tuple[date, date]]:
    from app.services.race.math import chunk_period

    return chunk_period(day_from, day_to, iiko_pull.BASELINE_WINDOW_DAYS)


@router.get("/learn/race/admin/tv-links", response_model=list[TvLinkOut])
async def list_tv_links(
    principal: Principal = Depends(_ADMIN),
    db: AsyncSession = Depends(get_db),
) -> list[TvLinkOut]:
    await _require_admin_access(db, principal)
    return [_tv_out(t) for t in await tv_token.list_tv_tokens(db, principal.tenant_id)]


@router.post("/learn/race/admin/tv-links", response_model=TvLinkOut, status_code=201)
async def create_tv_link(
    principal: Principal = Depends(_ADMIN),
    db: AsyncSession = Depends(get_db),
) -> TvLinkOut:
    await _require_admin_access(db, principal)
    row = await tv_token.create_tv_token(
        db, tenant_id=principal.tenant_id, actor_id=principal.employee_id
    )
    await db.commit()
    return _tv_out(row)


@router.delete("/learn/race/admin/tv-links/{token}", status_code=204)
async def revoke_tv_link(
    token: UUID,
    principal: Principal = Depends(_ADMIN),
    db: AsyncSession = Depends(get_db),
) -> None:
    await _require_admin_access(db, principal)
    await tv_token.revoke_tv_token(
        db, tenant_id=principal.tenant_id, token=token, actor_id=principal.employee_id
    )
    await db.commit()

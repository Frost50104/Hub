"""HR-профили API (Ф0 LMS): карточки сотрудников, архив, привязка, CSV-импорт.

Permissions:
- GET-список — scope-aware: hub:admin видит всех, ТУ/владелец франчайзи —
  сотрудников своих магазинов, остальные — только себя;
- мутации, unlinked-входы, импорт — hub:admin.

Карточки НЕ заводятся здесь (16.09, решение владельца: auth — единственный
источник штата). Писателей `employee_profiles` два — первый вход человека
(`ensure_profile_for_principal`) и staff-sync (`ensure_profile_for_staff_row`);
`POST /learn/employees` оставлен 410-заглушкой на два релиза для старых
PWA-бандлов.

CSV-импорт — ТОЛЬКО обновление HR-полей существующих карточек по email:
разделитель `;` или `,`, колонки email;phone;position;store;department;
franchisee;org_role;manager_email;hired_at (`full_name` допустима, но не
пишется — имя принадлежит auth). Пустая ячейка поле не трогает. Строка без
активной карточки — построчная ошибка, ничего не создаётся. Справочники
матчятся по имени; недостающие должности/отделы/франчайзи создаются, а
МАГАЗИН — нет: неизвестный магазин — построчная ошибка (create_missing_refs,
дефолт False с 05.09 — опечатка в названии бесшумно плодила магазины-дубли).
suppress_automations зарезервирован (Ф5).
"""

from __future__ import annotations

import csv
import io
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from signaris_auth import Principal
from sqlalchemy import delete, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.deps import enforce_rate_limit, get_db, require_auth
from app.models.employee_profile import EmployeeProfile, TuStoreAssignment
from app.models.org import Department, Franchisee, Position, Store
from app.models.shadow import AuthInvitation, ShadowUser
from app.schemas.employee import (
    ArchiveBody,
    ArchivedTwin,
    EmployeeListResponse,
    EmployeeResponse,
    EmployeeUpdate,
    ImportReport,
    InvitationResponse,
    LinkBody,
    RestoreBody,
    TuStoresReplace,
    UnlinkedLoginResponse,
)
from app.services import audit, hr_state
from app.services.audience_resolver import recalc_profile
from app.services.auth_state import auth_states_for_profiles
from app.services.employee_profiles import (
    archive_profile,
    find_latest_archived_by_email,
    normalize_email,
    restore_profile,
)
from app.services.learn_notify import notify_new_audience_members
from app.services.org_scope import resolve_scope
from app.services.people_search import match_condition

router = APIRouter(tags=["learn-employees"])

_ADMIN = require_auth(roles=["admin"])

_PROFILE_ORG_FIELDS = (
    "position_id",
    "store_id",
    "department_id",
    "franchisee_id",
    "org_role",
)


async def _get_profile_or_404(db: AsyncSession, profile_id: UUID) -> EmployeeProfile:
    profile = await db.get(EmployeeProfile, profile_id)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Карточка не найдена"
        )
    return profile


async def _frozen(db: AsyncSession, tenant_id: UUID) -> bool:
    return hr_state.is_frozen(await hr_state.load_state(db, tenant_id))


def _hr_locked(frozen: bool, profile: EmployeeProfile) -> bool:
    # Кассы заморозку не наследуют (16d, требование 7): их поля — Hub.
    return frozen and profile.account_kind == "person"


async def _refuse_in_window(db: AsyncSession, tenant_id: UUID) -> None:
    """Окно каткатa (ручная заморозка через CLI): между второй выгрузкой и
    импортом в auth любая правка карточек разошлась бы с копией в auth."""
    if hr_state.in_window(await hr_state.load_state(db, tenant_id)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=hr_state.HR_WINDOW_DETAIL)


async def _to_response(db: AsyncSession, profile: EmployeeProfile) -> EmployeeResponse:
    resp = EmployeeResponse.model_validate(profile)
    resp.hr_locked = _hr_locked(await _frozen(db, profile.tenant_id), profile)
    if profile.org_role == "tu":
        resp.tu_store_ids = [
            row[0]
            for row in await db.execute(
                select(TuStoreAssignment.store_id).where(
                    TuStoreAssignment.profile_id == profile.id
                )
            )
        ]
    return resp


# `staff_snapshot_fresh` и `auth_state_for` живут в `services/auth_state.py`
# (16.09): расчёт статуса один на «Сотрудников», «Прогресс» и CSV-выгрузку.


async def _to_responses(
    db: AsyncSession, profiles: list[EmployeeProfile]
) -> list[EmployeeResponse]:
    tu_ids = [p.id for p in profiles if p.org_role == "tu"]
    assignments: dict[UUID, list[UUID]] = {}
    if tu_ids:
        for profile_id, store_id in await db.execute(
            select(TuStoreAssignment.profile_id, TuStoreAssignment.store_id).where(
                TuStoreAssignment.profile_id.in_(tu_ids)
            )
        ):
            assignments.setdefault(profile_id, []).append(store_id)
    # Роль и статус учётки — один расчёт на оба экрана (`services/auth_state.py`,
    # 16.09): там же появляется «Приглашён(а)» по зеркалу `auth_invitations`.
    states = await auth_states_for_profiles(db, profiles)
    frozen = bool(profiles) and await _frozen(db, profiles[0].tenant_id)
    out = []
    for p in profiles:
        resp = EmployeeResponse.model_validate(p)
        resp.hr_locked = _hr_locked(frozen, p)
        resp.tu_store_ids = assignments.get(p.id, [])
        info = states.get(p.id)
        resp.hub_role = info.hub_role if info else None
        resp.auth_state = info.state if info else None
        out.append(resp)
    return out


@router.get("/learn/employees", response_model=EmployeeListResponse)
async def list_employees(
    status_filter: str | None = Query(default=None, alias="status"),
    q: str | None = Query(default=None, max_length=255),
    store_id: UUID | None = None,
    position_id: UUID | None = None,
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> EmployeeListResponse:
    scope = await resolve_scope(db, principal)
    # Кассы точек отсекаются НА СЕРВЕРЕ, чтобы `total` считался после
    # предиката: клиентский фильтр оставил бы `total` прежним, и
    # `employeeListCaption` навсегда переключился бы на «Показаны N из M —
    # уточните поиск». Управление карточкой кассы живёт в «Оргструктура →
    # Точки» (решение владельца 16.09).
    stmt = select(EmployeeProfile).where(EmployeeProfile.account_kind == "person")
    if scope.kind == "stores":
        stmt = stmt.where(
            or_(
                EmployeeProfile.store_id.in_(scope.store_ids or frozenset()),
                EmployeeProfile.id == scope.profile_id,
            )
        )
    elif scope.kind == "self":
        stmt = stmt.where(EmployeeProfile.id == (scope.profile_id or UUID(int=0)))

    if status_filter in ("active", "archived"):
        stmt = stmt.where(EmployeeProfile.status == status_filter)
    # Поиск — общий с упоминаниями (`people_search`): пословно и в любом
    # порядке. Прежняя одна подстрока не находила «Петров Иван», если в
    # карточке «Иван Петров», а порядок слов в справочнике смешанный.
    # Ранжирование здесь НЕ применяем: экран читает список страницами, и
    # порядок обязан оставаться тем же от страницы к странице.
    name_match = match_condition(EmployeeProfile.full_name, EmployeeProfile.email, q)
    if name_match is not None:
        stmt = stmt.where(name_match)
    if store_id is not None:
        stmt = stmt.where(EmployeeProfile.store_id == store_id)
    if position_id is not None:
        stmt = stmt.where(EmployeeProfile.position_id == position_id)

    total = (
        await db.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar_one()
    rows = (
        (
            await db.execute(
                # Тай-брейкер по `id` обязателен: клиент читает список
                # СТРАНИЦАМИ (`useEmployees` добирает набор до `total`), а на
                # неустойчивом порядке полные тёзки дают повторы и пропуски на
                # стыке страниц. Видимый порядок он не меняет — только разводит
                # одинаковые `full_name`.
                stmt.order_by(EmployeeProfile.full_name, EmployeeProfile.id)
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    # Метка последнего синка и приглашения (только admin-скоупу: остальным
    # список чужих приглашений не нужен и не положен).
    synced_at = (
        await db.execute(select(func.max(ShadowUser.staff_synced_at)))
    ).scalar_one_or_none()
    # Приглашения отдаём ТОЛЬКО те, у кого ещё нет активной карточки (16.09).
    # Раньше сюда шло зеркало целиком, и экран начинался со стены из 69 строк,
    # 62 из которых дублировали список под собой: у этих людей карточка есть и
    # стоит ниже с бейджем «Приглашён(а)» (`auth_state = invited` как раз и
    # значит «непривязанная карточка, почта в приглашениях»). Уникальны были
    # семь — те, у кого карточки нет вовсе, и именно они терялись в стене.
    #
    # Поиск применяем ТЕМ ЖЕ предикатом, что к карточкам: строка, которая не
    # слушается поиска, ведёт себя как приклеенная — ОС владельца 17.09
    # («фильтры влияют только на показ после этого блока»).
    invitations: list[AuthInvitation] = []
    if scope.kind == "all":
        inv_stmt = select(AuthInvitation).where(
            ~exists(
                select(EmployeeProfile.id).where(
                    func.lower(EmployeeProfile.email) == func.lower(AuthInvitation.email),
                    EmployeeProfile.status == "active",
                )
            )
        )
        inv_match = match_condition(AuthInvitation.full_name, AuthInvitation.email, q)
        if inv_match is not None:
            inv_stmt = inv_stmt.where(inv_match)
        invitations = list(
            (await db.execute(inv_stmt.order_by(AuthInvitation.email))).scalars()
        )
    return EmployeeListResponse(
        items=await _to_responses(db, list(rows)),
        total=total,
        staff_synced_at=synced_at,
        invitations=[InvitationResponse.model_validate(i) for i in invitations],
    )


@router.post("/learn/employees/sync")
async def trigger_staff_sync(
    dry_run: bool = Query(default=False),
    principal: Principal = Depends(_ADMIN),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """Ручной прогон staff-sync — кнопка «Обновить из auth».

    Возвращает счётчики (сколько карточек создано/привязано, конфликты) —
    при bootstrap админ видит масштаб, включая залп ознакомительных пушей
    новичкам. `available=false` = auth не отдаёт штат (нет ручки/доступа).

    Пока `staff_sync_enabled=false`, живой прогон ПРИНУДИТЕЛЬНО становится
    dry-run: флаг выключают ровно на время выката правок, и кнопка в обход
    него одним кликом устроила бы bootstrap с неотзываемой рассылкой —
    порядок включения из HUB_TASK_staff_endpoint_REPLY.md стал бы фикцией.

    Только своя организация: до 25.09 кнопка гоняла синк всех тенантов, и
    админ одной организации запускал его чужой и видел её счётчики.
    """
    from app.services import staff_sync

    effective_dry_run = dry_run or not get_settings().staff_sync_enabled
    report = await staff_sync.sync_staff(
        dry_run=effective_dry_run, only_tenant=principal.tenant_id
    )
    return {
        "available": report.available,
        "dry_run": report.dry_run,
        "shadows": report.shadows_upserted,
        "profiles_created": report.profiles_created,
        "profiles_linked": report.profiles_linked,
        "email_conflicts": report.email_conflicts,
        "archived_skips": report.archived_skips,
        "service_accounts": report.service_accounts,
        "inactive_skipped": report.inactive_skipped,
        "roles_cleared": report.roles_cleared,
        "archived": report.archived,
        "invitations": report.invitations,
        # Кадровые данные из auth (16d) — отчёт только своей организации:
        # числа и id, без ПДн. None — потребитель выключен или тенанта нет.
        "hr": report.hr.get(str(principal.tenant_id)),
    }


@router.get("/learn/employees/unlinked", response_model=list[UnlinkedLoginResponse])
async def list_unlinked_logins(
    principal: Principal = Depends(_ADMIN),
    db: AsyncSession = Depends(get_db),
) -> list[UnlinkedLoginResponse]:
    """Входы в Hub без HR-карточки (опечатка email при заведении и т.п.)."""
    rows = await db.execute(
        select(ShadowUser)
        .outerjoin(EmployeeProfile, EmployeeProfile.employee_id == ShadowUser.employee_id)
        .where(
            ShadowUser.deleted_at.is_(None),
            EmployeeProfile.id.is_(None),
            # Касса без карточки — не «опечатка в email», а штатное состояние:
            # карточки сервисным не заводятся вовсе. До этой правки экран на
            # проде на 100% состоял из таких строк, показывая проблему там,
            # где её нет.
            ShadowUser.account_kind.is_distinct_from("service"),
        )
        .order_by(ShadowUser.last_seen_at.desc())
    )
    return [
        UnlinkedLoginResponse(
            employee_id=u.employee_id,
            email=u.email,
            full_name=u.full_name,
            last_seen_at=u.last_seen_at,
        )
        for u in rows.scalars().all()
    ]


@router.get("/learn/employees/{profile_id}", response_model=EmployeeResponse)
async def get_employee(
    profile_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> EmployeeResponse:
    profile = await _get_profile_or_404(db, profile_id)
    scope = await resolve_scope(db, principal)
    visible = (
        scope.kind == "all"
        or profile.id == scope.profile_id
        or (scope.kind == "stores" and profile.store_id in (scope.store_ids or frozenset()))
    )
    if not visible:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Карточка не найдена")
    resp = await _to_response(db, profile)
    # Подсказка про архивную карточку с тем же адресом — только на АКТИВНОЙ и
    # только в одиночной ручке: в списке это стоило бы запроса на строку ради
    # случая, который встречается раз в несколько месяцев.
    if profile.status == "active":
        twin = await find_latest_archived_by_email(db, profile.email)
        if twin is not None:
            resp.archived_twin = ArchivedTwin.model_validate(twin)
    return resp


@router.post("/learn/employees", status_code=status.HTTP_410_GONE)
async def create_employee(principal: Principal = Depends(_ADMIN)) -> None:  # noqa: ARG001
    """Ручное заведение карточек закрыто 16.09 (решение владельца: auth —
    единственный источник штата). Заглушка, а не снятие маршрута: старый
    PWA-бандл с кнопкой «+ Сотрудник» получает русский текст вместо
    «Not Found» из глобального тоста. Снять через два релиза."""
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="Карточки сотрудников заводятся в auth — обновите приложение",
    )


@router.patch("/learn/employees/{profile_id}", response_model=EmployeeResponse)
async def update_employee(
    profile_id: UUID,
    body: EmployeeUpdate,
    principal: Principal = Depends(_ADMIN),
    db: AsyncSession = Depends(get_db),
) -> EmployeeResponse:
    profile = await _get_profile_or_404(db, profile_id)
    fields = body.model_dump(exclude_unset=True)
    if "email" in fields:
        fields["email"] = normalize_email(fields["email"])
    # Кадровые поля ведёт auth (16d): отказ только на ИЗМЕНЁННОЕ значение —
    # форма шлёт объект целиком, и вчерашние бандлы тоже; телефон и права
    # на контент правятся как раньше.
    state = await hr_state.load_state(db, profile.tenant_id)
    if _hr_locked(hr_state.is_frozen(state), profile) and hr_state.changed_hr_fields(
        profile, fields
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=hr_state.HR_WINDOW_DETAIL
            if hr_state.in_window(state)
            else hr_state.HR_FROZEN_DETAIL,
        )
    # Имя и email принадлежат auth: `_sync_linked_profile` перезапишет их при
    # следующем входе человека, поэтому правка здесь была бы принята, показана
    # применённой и молча пропала (ОС 28.08).
    #
    # Критерий — `last_activity_at`, а НЕ наличие `employee_id`: ручки /link и
    # /restore привязывают аккаунт без входа, и по employee_id карточка
    # замерзала бы с HR-именем, которое уже некому исправить.
    #
    # Отклоняется ОТЛИЧАЮЩЕЕСЯ значение, а не само присутствие поля: форма
    # редактора шлёт объект целиком, и на «присутствии» сломалось бы сохранение
    # должности, магазина и роли — у нового бандла и особенно у вчерашнего.
    if profile.last_activity_at is not None:
        for name, label in (("full_name", "Имя"), ("email", "Email")):
            if name in fields and fields[name] != getattr(profile, name):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        f"{label} сотрудника меняется в его профиле в auth — "
                        "оттуда Hub берёт его при следующем входе"
                    ),
                )
    diff: dict = {}
    org_changed = False
    for name, value in fields.items():
        old = getattr(profile, name)
        if old != value:
            diff[name] = {
                "old": str(old) if old is not None else None,
                "new": str(value) if value is not None else None,
            }
            setattr(profile, name, value)
            if name in _PROFILE_ORG_FIELDS:
                org_changed = True
    if not diff:
        return await _to_response(db, profile)
    await db.flush()
    # diffs инициализируется ДО ветки: PATCH без орг-полей (content_role,
    # телефон, status_text) и PATCH архивного профиля раньше падали 500
    # (UnboundLocalError) — QA-0821 #23.
    diffs: dict = {}
    if org_changed and profile.status == "active":
        # «Перевели в другой отдел — доступы меняются автоматически» (ТЗ §2.1).
        diffs = await recalc_profile(db, profile)
    await notify_new_audience_members(db, diffs)
    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor_id=principal.employee_id,
        action="update",
        object_type="employee_profile",
        object_id=profile.id,
        object_label=profile.full_name,
        diff=diff,
    )
    await db.commit()
    await db.refresh(profile)
    return await _to_response(db, profile)


@router.put("/learn/employees/{profile_id}/tu-stores", response_model=EmployeeResponse)
async def replace_tu_stores(
    profile_id: UUID,
    body: TuStoresReplace,
    principal: Principal = Depends(_ADMIN),
    db: AsyncSession = Depends(get_db),
) -> EmployeeResponse:
    profile = await _get_profile_or_404(db, profile_id)
    if _hr_locked(await _frozen(db, profile.tenant_id), profile):
        current = set(
            (
                await db.execute(
                    select(TuStoreAssignment.store_id).where(
                        TuStoreAssignment.profile_id == profile_id
                    )
                )
            ).scalars()
        )
        if current == set(body.store_ids):
            # Форма зовёт эту ручку при каждом сохранении ТУ — тот же набор
            # проходит без перезаписи, иначе сохранение телефона ломалось бы.
            return await _to_response(db, profile)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=hr_state.HR_TU_DETAIL,
        )
    if profile.org_role != "tu":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Закреплённые магазины настраиваются только для ТУ",
        )
    await db.execute(
        delete(TuStoreAssignment).where(TuStoreAssignment.profile_id == profile_id)
    )
    for store_id in dict.fromkeys(body.store_ids):
        db.add(
            TuStoreAssignment(
                tenant_id=principal.tenant_id, profile_id=profile_id, store_id=store_id
            )
        )
    await db.flush()
    diffs = await recalc_profile(db, profile)
    await notify_new_audience_members(db, diffs)
    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor_id=principal.employee_id,
        action="access_change",
        object_type="employee_profile",
        object_id=profile.id,
        object_label=profile.full_name,
        diff={"tu_stores_count": {"old": None, "new": len(set(body.store_ids))}},
    )
    await db.commit()
    await db.refresh(profile)
    return await _to_response(db, profile)


@router.post("/learn/employees/{profile_id}/archive", response_model=EmployeeResponse)
async def archive_employee(
    profile_id: UUID,
    body: ArchiveBody,
    principal: Principal = Depends(_ADMIN),
    db: AsyncSession = Depends(get_db),
) -> EmployeeResponse:
    profile = await _get_profile_or_404(db, profile_id)
    await _refuse_in_window(db, principal.tenant_id)
    await archive_profile(db, profile, reason=body.reason, actor_id=principal.employee_id)
    await db.commit()
    await db.refresh(profile)
    return await _to_response(db, profile)


@router.post("/learn/employees/{profile_id}/restore", response_model=EmployeeResponse)
async def restore_employee(
    profile_id: UUID,
    body: RestoreBody,
    principal: Principal = Depends(_ADMIN),
    db: AsyncSession = Depends(get_db),
) -> EmployeeResponse:
    profile = await _get_profile_or_404(db, profile_id)
    state = await hr_state.load_state(db, principal.tenant_id)
    if hr_state.in_window(state):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=hr_state.HR_WINDOW_DETAIL)
    if (
        hr_state.is_frozen(state)
        and profile.archive_reason == "auth_deactivated"
        and profile.employee_id is not None
    ):
        # Карточку вернёт синк, когда учётку включат в auth. Восстановленная
        # руками при отключённой учётке через тик снова ушла бы в архив — с
        # пушами обязательных курсов в промежутке (старые бандлы кнопку видят).
        auth_active = (
            await db.execute(
                select(ShadowUser.auth_active).where(
                    ShadowUser.employee_id == profile.employee_id
                )
            )
        ).scalar_one_or_none()
        if auth_active is not True:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=hr_state.HR_RESTORE_DEACTIVATED_DETAIL,
            )
    try:
        await restore_profile(
            db, profile, actor_id=principal.employee_id, new_employee_id=body.employee_id
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from None
    await db.commit()
    await db.refresh(profile)
    return await _to_response(db, profile)


@router.post("/learn/employees/{profile_id}/link", response_model=EmployeeResponse)
async def link_employee_login(
    profile_id: UUID,
    body: LinkBody,
    principal: Principal = Depends(_ADMIN),
    db: AsyncSession = Depends(get_db),
) -> EmployeeResponse:
    """Привязать «непривязанный вход» к существующей активной карточке."""
    profile = await _get_profile_or_404(db, profile_id)
    await _refuse_in_window(db, principal.tenant_id)
    if profile.status != "active":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Карточка в архиве — используйте восстановление",
        )
    if profile.employee_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Карточка уже привязана к входу"
        )
    holder = (
        await db.execute(
            select(EmployeeProfile.id).where(EmployeeProfile.employee_id == body.employee_id)
        )
    ).scalar_one_or_none()
    if holder is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Этот вход уже привязан к другой карточке",
        )
    profile.employee_id = body.employee_id
    await db.flush()
    diffs = await recalc_profile(db, profile)
    await notify_new_audience_members(db, diffs)
    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor_id=principal.employee_id,
        action="update",
        object_type="employee_profile",
        object_id=profile.id,
        object_label=profile.full_name,
        diff={"employee_id": {"old": None, "new": str(body.employee_id)}},
    )
    await db.commit()
    await db.refresh(profile)
    return await _to_response(db, profile)


# --- CSV-импорт ---------------------------------------------------------------

_IMPORT_COLUMNS = frozenset(
    {
        "email",
        "full_name",
        "phone",
        "position",
        "store",
        "department",
        "franchisee",
        "org_role",
        "manager_email",
        "hired_at",
    }
)
_ORG_ROLES = ("employee", "tu", "franchisee_owner", "office")


@router.post("/learn/employees/import", response_model=ImportReport)
async def import_employees(
    file: UploadFile = File(...),
    dry_run: bool = Query(default=False),
    # Дефолт False с 05.09 (задача auth import_no_autocreate): опечатка в
    # названии магазина бесшумно порождала магазин-дубль без кода и адреса —
    # неизвестный магазин теперь построчная ошибка. Гейтит ТОЛЬКО Store:
    # автосоздание должностей/отделов/франчайзи — рабочий сценарий онбординга.
    create_missing_refs: bool = Query(default=False),
    suppress_automations: bool = Query(default=True),  # noqa: ARG001 — включится в Ф5
    principal: Principal = Depends(_ADMIN),
    db: AsyncSession = Depends(get_db),
) -> ImportReport:
    """Обновить HR-поля СУЩЕСТВУЮЩИХ карточек из CSV (update-only с 16.09).

    Карточек импорт не создаёт: строка без активной карточки — построчная
    ошибка, и до справочников она не доходит (иначе опечатка в почте плодила
    бы должности как побочный эффект). Пустая ячейка поле не трогает —
    частичный файл «email;position» не должен сбрасывать ТУ в линейных и
    обнулять отделы. Имя и почта из CSV не пишутся: ими владеет auth.

    В конце — `rebuild_tenant` + `notify_new_audience_members`, как и раньше:
    смена должности или точки меняет аудитории, а новым членам уходят
    назначения обязательных курсов. Пуши неотзываемы — dry-run обязателен.
    """
    await enforce_rate_limit(
        bucket="employee:import", employee_id=str(principal.employee_id), limit=5, window_sec=60
    )
    raw = await file.read()
    if len(raw) > 2 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="CSV больше 2 МБ")
    try:
        text_data = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text_data = raw.decode("cp1251")

    first_line = text_data.splitlines()[0] if text_data.splitlines() else ""
    delimiter = ";" if first_line.count(";") >= first_line.count(",") else ","
    reader = csv.DictReader(io.StringIO(text_data), delimiter=delimiter)
    if not reader.fieldnames or "email" not in [f.strip() for f in reader.fieldnames]:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="CSV должен содержать колонку email (разделитель ; или ,)",
        )

    # Справочники по имени (lower) — один раз.
    async def _ref_map(model):  # noqa: ANN001, ANN202
        rows = (await db.execute(select(model))).scalars().all()
        return {r.name.strip().lower(): r for r in rows}

    positions = await _ref_map(Position)
    stores = await _ref_map(Store)
    departments = await _ref_map(Department)
    franchisees = await _ref_map(Franchisee)
    # Кадровые данные ведёт auth (16d): у карточек людей кадровые колонки не
    # пишутся, справочники по имени не создаются. Кассы — как раньше.
    frozen = await _frozen(db, principal.tenant_id)
    frozen_row = "кадровые данные сотрудника ведутся в auth — в файле оставьте email и телефон"

    # Карточки по почте — активные обновляем, архивные называем отдельно:
    # «карточки нет — заводится в auth» про архивную было бы неправдой.
    profiles_by_email: dict[str, EmployeeProfile] = {
        normalize_email(p.email): p
        for p in (
            await db.execute(
                select(EmployeeProfile).where(EmployeeProfile.status == "active")
            )
        ).scalars()
    }
    archived_emails = {
        row[0]
        for row in await db.execute(
            select(func.lower(EmployeeProfile.email)).where(
                EmployeeProfile.status == "archived"
            )
        )
    }

    changed: set[UUID] = set()
    skipped = 0
    errors: list[str] = []
    pending_managers: list[tuple[EmployeeProfile, str]] = []

    def _apply(profile: EmployeeProfile, field: str, value: object) -> None:
        # Считаем людей, а не строки: дубль email в файле — одна карточка.
        if getattr(profile, field) != value:
            setattr(profile, field, value)
            changed.add(profile.id)

    def _resolve_ref(  # noqa: ANN202
        kind: str,
        name_map: dict,  # noqa: ANN001
        model,  # noqa: ANN001
        raw_name: str,
        *,
        allow_create: bool = True,
    ):
        key = raw_name.strip().lower()
        if not key:
            return None
        if key in name_map:
            return name_map[key]
        if not allow_create:
            raise ValueError(f"{kind} «{raw_name.strip()}» не найден")
        row = model(tenant_id=principal.tenant_id, name=raw_name.strip())
        db.add(row)
        name_map[key] = row
        return row

    for line_no, row in enumerate(reader, start=2):
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        unknown = set(row) - _IMPORT_COLUMNS - {""}
        if unknown and line_no == 2:
            errors.append(f"Неизвестные колонки игнорируются: {', '.join(sorted(unknown))}")
        email = normalize_email(row.get("email", ""))
        if not email or "@" not in email:
            errors.append(f"Строка {line_no}: пустой или некорректный email")
            continue
        profile = profiles_by_email.get(email)
        if profile is None:
            if email in archived_emails:
                errors.append(
                    f"Строка {line_no}: карточка с email «{email}» в архиве — восстановите её"
                )
            else:
                errors.append(
                    f"Строка {line_no}: карточки с email «{email}» нет — "
                    "учётные записи заводятся в auth"
                )
            skipped += 1
            continue
        org_role = row.get("org_role") or profile.org_role
        if org_role not in _ORG_ROLES:
            errors.append(f"Строка {line_no}: неизвестная org_role «{org_role}»")
            continue
        hired_at: date | None = None
        if row.get("hired_at"):
            try:
                hired_at = date.fromisoformat(row["hired_at"])
            except ValueError:
                errors.append(f"Строка {line_no}: hired_at не в формате YYYY-MM-DD")
                continue
        try:
            position = _resolve_ref(
                "Должность", positions, Position, row.get("position", ""), allow_create=not frozen
            )
            store = _resolve_ref(
                "Магазин",
                stores,
                Store,
                row.get("store", ""),
                allow_create=create_missing_refs,
            )
            department = _resolve_ref(
                "Отдел", departments, Department, row.get("department", ""), allow_create=not frozen
            )
            franchisee = _resolve_ref(
                "Франчайзи",
                franchisees,
                Franchisee,
                row.get("franchisee", ""),
                allow_create=not frozen,
            )
        except ValueError as e:
            suffix = " (справочники ведутся в auth)" if frozen else ""
            errors.append(f"Строка {line_no}: {e}{suffix}")
            continue

        if _hr_locked(frozen, profile):
            wanted: dict[str, object] = {"org_role": org_role}
            if hired_at is not None:
                wanted["hired_at"] = hired_at
            if position is not None:
                wanted["position_id"] = position.id
            if store is not None:
                wanted["store_id"] = store.id
            if department is not None:
                wanted["department_id"] = department.id
            if franchisee is not None and org_role == "franchisee_owner":
                wanted["franchisee_id"] = franchisee.id
            if hr_state.changed_hr_fields(profile, wanted):
                errors.append(f"Строка {line_no}: {frozen_row}")
                continue

        await db.flush()  # id для только что созданных справочников
        if row.get("phone"):
            _apply(profile, "phone", row["phone"])
        _apply(profile, "org_role", org_role)
        if hired_at is not None:
            _apply(profile, "hired_at", hired_at)
        if position is not None:
            _apply(profile, "position_id", position.id)
        if store is not None:
            _apply(profile, "store_id", store.id)
        if department is not None:
            _apply(profile, "department_id", department.id)
        if franchisee is not None and org_role == "franchisee_owner":
            _apply(profile, "franchisee_id", franchisee.id)
        if row.get("manager_email"):
            pending_managers.append((profile, normalize_email(row["manager_email"])))

    # Руководители — вторым проходом (могут идти ниже по файлу).
    manager_ids: dict[str, UUID] = {
        row[1]: row[0]
        for row in await db.execute(
            select(EmployeeProfile.id, func.lower(EmployeeProfile.email)).where(
                EmployeeProfile.status == "active"
            )
        )
    }
    for profile, manager_email in pending_managers:
        manager_id = manager_ids.get(manager_email)
        if manager_id is None:
            errors.append(f"{profile.email}: руководитель {manager_email} не найден")
        elif _hr_locked(frozen, profile) and manager_id != profile.manager_profile_id:
            errors.append(f"{profile.email}: руководитель — {frozen_row}")
        else:
            _apply(profile, "manager_profile_id", manager_id)

    updated = len(changed)
    if dry_run:
        await db.rollback()
        return ImportReport(updated=updated, skipped=skipped, errors=errors, dry_run=True)

    # Сессия autoflush=False: без flush пересчёт аудиторий не увидел бы
    # присвоенных полей (в том числе руководителей второго прохода).
    await db.flush()

    from app.services.audience_resolver import rebuild_tenant

    rebuild_diffs = await rebuild_tenant(db, principal.tenant_id)
    await notify_new_audience_members(db, rebuild_diffs)
    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor_id=principal.employee_id,
        action="import",
        object_type="employee_profile",
        object_label=file.filename or "import.csv",
        diff={"updated": {"old": None, "new": updated}, "skipped": {"old": None, "new": skipped}},
    )
    await db.commit()
    return ImportReport(updated=updated, skipped=skipped, errors=errors, dry_run=False)

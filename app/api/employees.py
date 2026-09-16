"""HR-профили API (Ф0 LMS): карточки сотрудников, архив, привязка, CSV-импорт.

Permissions:
- GET-список — scope-aware: hub:admin видит всех, ТУ/владелец франчайзи —
  сотрудников своих магазинов, остальные — только себя;
- мутации, unlinked-входы, импорт — hub:admin.

CSV-импорт (онбординг UPPETIT, 200+ людей): разделитель `;` или `,`,
колонки email;full_name;phone;position;store;department;franchisee;org_role;
manager_email;hired_at (обязательны только email и full_name). Справочники
матчятся по имени; недостающие должности/отделы/франчайзи создаются, а
МАГАЗИН — нет: неизвестный магазин — построчная ошибка (create_missing_refs,
дефолт False с 05.09 — опечатка в названии бесшумно плодила магазины-дубли).
Существующие active-email пропускаются. suppress_automations зарезервирован
(Ф5) — bulk не должен триггерить welcome-сценарии ветеранам.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, date, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from signaris_auth import Principal
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.deps import get_db, require_auth
from app.models.employee_profile import EmployeeProfile, TuStoreAssignment
from app.models.org import Department, Franchisee, Position, Store
from app.models.shadow import AuthInvitation, ShadowUser
from app.schemas.employee import (
    ArchiveBody,
    ArchivedTwin,
    EmployeeCreate,
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
from app.services import audit
from app.services.audience_resolver import recalc_profile
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


async def _to_response(db: AsyncSession, profile: EmployeeProfile) -> EmployeeResponse:
    resp = EmployeeResponse.model_validate(profile)
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


def staff_snapshot_fresh(
    last_synced_at: datetime | None, *, now: datetime, interval_sec: float
) -> bool:
    """Снимок auth живой = не старше двух интервалов воркера (совет auth).

    «Был хоть один синк» — залипающий флаг: сломайся ключ, экран неделю
    уверенно писал бы «без учётки» по устаревшему снимку. Протухший снимок
    откатывает статусы к осторожному «не привязан(а)»."""
    if last_synced_at is None:
        return False
    return (now - last_synced_at).total_seconds() <= 2 * interval_sec


def auth_state_for(
    *,
    employee_id: UUID | None,
    last_activity_at: object,
    shadow_deleted: bool,
    auth_active: bool | None,
    staff_synced: bool,
) -> str:
    """Честный статус учётки для карточки — ОДНА функция вместо двух
    рассинхронённых признаков в JSX (бейдж считался по employee_id, заморозка
    по last_activity_at — восстановленная карточка показывалась «не входил»
    с замороженными полями).

    До первого staff-sync утверждать «без учётки» нельзя: непривязанная
    карточка может принадлежать человеку с живой учёткой, который просто не
    входил, — до синка отдаём осторожное `not_linked`."""
    if employee_id is None:
        return "no_account" if staff_synced else "not_linked"
    if shadow_deleted:
        return "deleted"
    if auth_active is False:
        return "blocked"
    if last_activity_at is None:
        return "not_logged_in"
    return "active"


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
    # Кеш auth одним запросом на страницу (staff-sync, 0052).
    settings = get_settings()
    staff_synced = staff_snapshot_fresh(
        (await db.execute(select(func.max(ShadowUser.staff_synced_at)))).scalar_one_or_none(),
        now=datetime.now(UTC),
        interval_sec=settings.staff_sync_interval_sec,
    )
    employee_ids = [p.employee_id for p in profiles if p.employee_id is not None]
    shadows: dict[UUID, tuple[str | None, bool, bool | None]] = {}
    if employee_ids:
        for eid, hub_role, deleted_at, auth_active in await db.execute(
            select(
                ShadowUser.employee_id,
                ShadowUser.hub_role,
                ShadowUser.deleted_at,
                ShadowUser.auth_active,
            ).where(ShadowUser.employee_id.in_(employee_ids))
        ):
            shadows[eid] = (hub_role, deleted_at is not None, auth_active)
    out = []
    for p in profiles:
        resp = EmployeeResponse.model_validate(p)
        resp.tu_store_ids = assignments.get(p.id, [])
        hub_role, shadow_deleted, auth_active = shadows.get(
            p.employee_id, (None, False, None)
        ) if p.employee_id else (None, False, None)
        resp.hub_role = hub_role
        resp.auth_state = auth_state_for(
            employee_id=p.employee_id,
            last_activity_at=p.last_activity_at,
            shadow_deleted=shadow_deleted,
            auth_active=auth_active,
            staff_synced=staff_synced,
        )
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
    invitations: list[AuthInvitation] = []
    if scope.kind == "all":
        invitations = list(
            (
                await db.execute(
                    select(AuthInvitation).order_by(AuthInvitation.email)
                )
            ).scalars()
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
    """
    from app.services.staff_sync import sync_staff

    effective_dry_run = dry_run or not get_settings().staff_sync_enabled
    report = await sync_staff(dry_run=effective_dry_run)
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


@router.post("/learn/employees", response_model=EmployeeResponse, status_code=201)
async def create_employee(
    body: EmployeeCreate,
    principal: Principal = Depends(_ADMIN),
    db: AsyncSession = Depends(get_db),
) -> EmployeeResponse:
    email = normalize_email(body.email)
    dup = (
        await db.execute(
            select(EmployeeProfile.id).where(
                func.lower(EmployeeProfile.email) == email,
                EmployeeProfile.status == "active",
            )
        )
    ).scalar_one_or_none()
    if dup is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Активная карточка с этим email уже существует",
        )
    profile = EmployeeProfile(
        tenant_id=principal.tenant_id,
        email=email,
        full_name=body.full_name,
        phone=body.phone,
        position_id=body.position_id,
        store_id=body.store_id,
        department_id=body.department_id,
        franchisee_id=body.franchisee_id,
        manager_profile_id=body.manager_profile_id,
        org_role=body.org_role,
        content_role=body.content_role,
        hired_at=body.hired_at,
        created_by=principal.employee_id,
    )
    db.add(profile)
    await db.flush()
    diffs = await recalc_profile(db, profile)
    await notify_new_audience_members(db, diffs)
    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor_id=principal.employee_id,
        action="create",
        object_type="employee_profile",
        object_id=profile.id,
        object_label=profile.full_name,
    )
    await db.commit()
    await db.refresh(profile)
    return await _to_response(db, profile)


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

    existing_emails = {
        row[0]
        for row in await db.execute(
            select(func.lower(EmployeeProfile.email)).where(
                EmployeeProfile.status == "active"
            )
        )
    }

    created = 0
    skipped = 0
    errors: list[str] = []
    pending_managers: list[tuple[EmployeeProfile, str]] = []
    profiles_by_email: dict[str, EmployeeProfile] = {}

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
        row = { (k or "").strip().lower(): (v or "").strip() for k, v in row.items() }
        unknown = set(row) - _IMPORT_COLUMNS - {""}
        if unknown and line_no == 2:
            errors.append(f"Неизвестные колонки игнорируются: {', '.join(sorted(unknown))}")
        email = normalize_email(row.get("email", ""))
        full_name = row.get("full_name", "")
        if not email or "@" not in email:
            errors.append(f"Строка {line_no}: пустой или некорректный email")
            continue
        if not full_name:
            errors.append(f"Строка {line_no}: пустое full_name")
            continue
        if email in existing_emails:
            skipped += 1
            continue
        org_role = row.get("org_role") or "employee"
        if org_role not in ("employee", "tu", "franchisee_owner", "office"):
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
            position = _resolve_ref("Должность", positions, Position, row.get("position", ""))
            store = _resolve_ref(
                "Магазин",
                stores,
                Store,
                row.get("store", ""),
                allow_create=create_missing_refs,
            )
            department = _resolve_ref(
                "Отдел", departments, Department, row.get("department", "")
            )
            franchisee = _resolve_ref(
                "Франчайзи", franchisees, Franchisee, row.get("franchisee", "")
            )
        except ValueError as e:
            errors.append(f"Строка {line_no}: {e}")
            continue

        await db.flush()  # id для только что созданных справочников
        profile = EmployeeProfile(
            tenant_id=principal.tenant_id,
            email=email,
            full_name=full_name,
            phone=row.get("phone") or None,
            position_id=position.id if position else None,
            store_id=store.id if store else None,
            department_id=department.id if department else None,
            franchisee_id=franchisee.id if franchisee and org_role == "franchisee_owner" else None,
            org_role=org_role,
            hired_at=hired_at,
            created_by=principal.employee_id,
        )
        db.add(profile)
        existing_emails.add(email)
        profiles_by_email[email] = profile
        if row.get("manager_email"):
            pending_managers.append((profile, normalize_email(row["manager_email"])))
        created += 1

    await db.flush()

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
        else:
            profile.manager_profile_id = manager_id

    if dry_run:
        await db.rollback()
        return ImportReport(created=created, skipped=skipped, errors=errors, dry_run=True)

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
        diff={"created": {"old": None, "new": created}, "skipped": {"old": None, "new": skipped}},
    )
    await db.commit()
    return ImportReport(created=created, skipped=skipped, errors=errors, dry_run=False)

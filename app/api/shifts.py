"""Биржа смен API (Ф7, ТЗ §24).

Роли:
- сотрудник: видит open-смены СВОЕЙ должности (+ свои отклики/назначения),
  откликается/отзывает; матчинг проверяет сервер (active + должность +
  завершённые required-курсы);
- менеджер (org_scope stores: ТУ/франчайзи-владелец; hub-admin — все):
  публикует смены своих магазинов, принимает отклики, завершает/отменяет.

auto_confirm: первый прошедший проверки отклик назначается сразу.
Гео-скоуп v1 упрощён: смена видна всем подходящим по должности в tenant'е
(магазин показан в карточке) — фильтр «по городу» отложен.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from signaris_auth import Principal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import enforce_rate_limit, get_db, require_auth
from app.models.course import Course
from app.models.employee_profile import EmployeeProfile
from app.models.org import Position, Store
from app.models.progress import CourseProgress
from app.models.shift import ShiftApplication, ShiftPosting
from app.services import audit
from app.services.learn_notify import _employee_ids
from app.services.notify_batch import notify_many
from app.services.org_scope import get_profile, resolve_scope
from app.services.timefmt import fmt_range

router = APIRouter(tags=["learn-shifts"])


# ─── Схемы ───────────────────────────────────────────────────────────────────


class PostingCreate(BaseModel):
    store_id: UUID
    position_id: UUID
    starts_at: datetime
    ends_at: datetime
    pay_note: str | None = Field(default=None, max_length=255)
    note: str | None = Field(default=None, max_length=2000)
    required_course_ids: list[UUID] = Field(default_factory=list, max_length=10)
    auto_confirm: bool = False


class CourseRef(BaseModel):
    id: UUID
    title: str


class ApplicationView(BaseModel):
    id: UUID
    profile_id: UUID
    employee_name: str | None = None
    position_name: str | None = None
    status: str
    comment: str | None
    created_at: datetime
    # Все required-курсы смены завершены кандидатом (на момент отдачи: отклик
    # проверяет это при подаче, но набор курсов могли изменить PATCH'ем позже).
    passed_required: bool = True


class PostingView(BaseModel):
    id: UUID
    store_id: UUID
    store_name: str | None = None
    position_id: UUID
    position_name: str | None = None
    starts_at: datetime
    ends_at: datetime
    pay_note: str | None
    note: str | None
    required_course_ids: list[UUID]
    required_course_titles: list[str] = []
    auto_confirm: bool
    status: str
    assigned_profile_id: UUID | None
    assigned_name: str | None = None
    created_at: datetime
    # Персональное:
    my_application_status: str | None = None
    can_apply: bool = False
    # Названия — legacy для старых бандлов; `missing` — с id для ссылки «К курсу».
    missing_courses: list[str] = []
    missing: list[CourseRef] = []
    # Менеджеру:
    applications: list[ApplicationView] | None = None


class ShiftListResponse(BaseModel):
    items: list[PostingView]
    can_manage: bool
    # Должность текущего сотрудника — подпись «моя должность — бариста» в шапке.
    my_position_name: str | None = None


class PostingUpdate(BaseModel):
    """Правка ОТКРЫТОЙ смены. Магазин и должность не меняются: по ним уже
    разосланы уведомления и поданы отклики — это другая смена."""

    starts_at: datetime | None = None
    ends_at: datetime | None = None
    pay_note: str | None = Field(default=None, max_length=255)
    note: str | None = Field(default=None, max_length=2000)
    required_course_ids: list[UUID] | None = Field(default=None, max_length=10)
    auto_confirm: bool | None = None


class ApplyBody(BaseModel):
    comment: str | None = Field(default=None, max_length=500)


# ─── Хелперы ─────────────────────────────────────────────────────────────────


async def _manager_store_ids(
    db: AsyncSession, principal: Principal
) -> frozenset[UUID] | None:
    """None = все магазины (admin); frozenset = свои; HTTPException — не менеджер."""
    scope = await resolve_scope(db, principal)
    if scope.kind == "all":
        return None
    if scope.kind == "stores" and scope.store_ids:
        return scope.store_ids
    raise HTTPException(
        status_code=403, detail="Публиковать смены могут руководители магазинов"
    )


async def _get_posting_or_404(db: AsyncSession, posting_id: UUID) -> ShiftPosting:
    posting = await db.get(ShiftPosting, posting_id)
    if posting is None:
        raise HTTPException(status_code=404, detail="Смена не найдена")
    return posting


async def _require_posting_manager(
    db: AsyncSession, principal: Principal, posting: ShiftPosting
) -> None:
    store_ids = await _manager_store_ids(db, principal)
    if store_ids is not None and posting.store_id not in store_ids:
        raise HTTPException(status_code=403, detail="Это смена не вашего магазина")


async def _missing_courses(
    db: AsyncSession, posting: ShiftPosting, profile_id: UUID
) -> list[CourseRef]:
    """Required-курсы (id + название), которые кандидат ещё не завершил."""
    if not posting.required_course_ids:
        return []
    completed = {
        r[0]
        for r in await db.execute(
            select(CourseProgress.course_id).where(
                CourseProgress.profile_id == profile_id,
                CourseProgress.course_id.in_(posting.required_course_ids),
                CourseProgress.completed_at.is_not(None),
            )
        )
    }
    missing_ids = [c for c in posting.required_course_ids if c not in completed]
    if not missing_ids:
        return []
    refs = [
        CourseRef(id=r[0], title=r[1])
        for r in await db.execute(
            select(Course.id, Course.title).where(Course.id.in_(missing_ids))
        )
    ]
    # Удалённый курс требованием остаётся (чужой id), но имени у него нет.
    return refs or [CourseRef(id=missing_ids[0], title="курс удалён")]


async def _notify_profiles(
    db: AsyncSession,
    posting: ShiftPosting,
    profile_ids: list[UUID],
    *,
    kind: str,
    title: str,
    body: str,
) -> None:
    recipients = await _employee_ids(db, profile_ids)
    await notify_many(
        db,
        tenant_id=posting.tenant_id,
        employee_ids=list(recipients.values()),
        kind=kind,
        title=title,
        body=body,
        url="/learn/shifts",
        payload={"posting_id": str(posting.id)},
    )


def _fmt_when(posting: ShiftPosting) -> str:
    # Человеку — локальное время сети (settings.display_timezone), не UTC:
    # «30.08 08:00–16:00 UTC» при 10:00–18:00 в интерфейсе — QA-0821 #27.
    return fmt_range(posting.starts_at, posting.ends_at)


# ─── Списки ──────────────────────────────────────────────────────────────────


@router.get("/learn/shifts", response_model=ShiftListResponse)
async def list_shifts(
    manage: bool = Query(default=False),
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> ShiftListResponse:
    profile = await get_profile(db, principal)

    can_manage = False
    manager_stores: frozenset[UUID] | None = None
    try:
        manager_stores = await _manager_store_ids(db, principal)
        can_manage = True
    except HTTPException:
        can_manage = False

    if manage and can_manage:
        stmt = select(ShiftPosting)
        if manager_stores is not None:
            stmt = stmt.where(ShiftPosting.store_id.in_(manager_stores))
        postings = list(
            (
                await db.execute(stmt.order_by(ShiftPosting.starts_at.desc()).limit(100))
            )
            .scalars()
            .all()
        )
    else:
        if profile is None:
            return ShiftListResponse(items=[], can_manage=can_manage)
        # Сотрудник: открытые смены моей должности + всё, где я участвую.
        my_posting_ids = select(ShiftApplication.posting_id).where(
            ShiftApplication.profile_id == profile.id
        )
        stmt = (
            select(ShiftPosting)
            .where(
                (
                    (ShiftPosting.status == "open")
                    & (ShiftPosting.position_id == (profile.position_id or UUID(int=0)))
                    & (ShiftPosting.ends_at > datetime.now(UTC))
                )
                | ShiftPosting.id.in_(my_posting_ids)
                | (ShiftPosting.assigned_profile_id == profile.id)
            )
            .order_by(ShiftPosting.starts_at)
            .limit(100)
        )
        postings = list((await db.execute(stmt)).scalars().all())

    my_position_name = None
    if profile is not None and profile.position_id is not None:
        my_position_name = (
            await db.execute(select(Position.name).where(Position.id == profile.position_id))
        ).scalar_one_or_none()
    return ShiftListResponse(
        items=await _render_postings(
            db,
            postings,
            profile=profile,
            include_applications=manage and can_manage,
        ),
        can_manage=can_manage,
        my_position_name=my_position_name,
    )


async def _render_postings(
    db: AsyncSession,
    postings: list[ShiftPosting],
    *,
    profile: EmployeeProfile | None,
    include_applications: bool,
) -> list[PostingView]:
    if not postings:
        return []
    store_names = {
        r[0]: r[1]
        for r in await db.execute(
            select(Store.id, Store.name).where(
                Store.id.in_({p.store_id for p in postings})
            )
        )
    }
    position_names = {
        r[0]: r[1]
        for r in await db.execute(
            select(Position.id, Position.name).where(
                Position.id.in_({p.position_id for p in postings})
            )
        )
    }
    course_ids = {cid for p in postings for cid in p.required_course_ids}
    course_titles = {}
    if course_ids:
        course_titles = {
            r[0]: r[1]
            for r in await db.execute(
                select(Course.id, Course.title).where(Course.id.in_(course_ids))
            )
        }
    assigned_ids = {p.assigned_profile_id for p in postings if p.assigned_profile_id}
    assigned_names = {}
    if assigned_ids:
        assigned_names = {
            r[0]: r[1]
            for r in await db.execute(
                select(EmployeeProfile.id, EmployeeProfile.full_name).where(
                    EmployeeProfile.id.in_(assigned_ids)
                )
            )
        }

    my_apps: dict[UUID, str] = {}
    if profile is not None:
        my_apps = {
            r[0]: r[1]
            for r in await db.execute(
                select(ShiftApplication.posting_id, ShiftApplication.status).where(
                    ShiftApplication.profile_id == profile.id,
                    ShiftApplication.posting_id.in_([p.id for p in postings]),
                )
            )
        }

    all_apps: dict[UUID, list[ApplicationView]] = {}
    if include_applications:
        posting_by_id = {p.id: p for p in postings}
        rows = (
            await db.execute(
                select(ShiftApplication, EmployeeProfile.full_name, EmployeeProfile.position_id)
                .join(EmployeeProfile, EmployeeProfile.id == ShiftApplication.profile_id)
                .where(ShiftApplication.posting_id.in_([p.id for p in postings]))
                .order_by(ShiftApplication.created_at)
            )
        ).all()
        # Кто из кандидатов закрыл required-курсы своей смены — одним запросом.
        req_pairs = {
            (app_row.profile_id, cid)
            for app_row, _name, _pos in rows
            for cid in (posting_by_id[app_row.posting_id].required_course_ids or [])
        }
        completed_pairs: set[tuple[UUID, UUID]] = set()
        if req_pairs:
            completed_pairs = {
                (r[0], r[1])
                for r in await db.execute(
                    select(CourseProgress.profile_id, CourseProgress.course_id).where(
                        CourseProgress.profile_id.in_({pid for pid, _ in req_pairs}),
                        CourseProgress.course_id.in_({cid for _, cid in req_pairs}),
                        CourseProgress.completed_at.is_not(None),
                    )
                )
            }
        for app_row, name, pos_id in rows:
            required = posting_by_id[app_row.posting_id].required_course_ids or []
            all_apps.setdefault(app_row.posting_id, []).append(
                ApplicationView(
                    id=app_row.id,
                    profile_id=app_row.profile_id,
                    employee_name=name,
                    position_name=position_names.get(pos_id) if pos_id else None,
                    status=app_row.status,
                    comment=app_row.comment,
                    created_at=app_row.created_at,
                    passed_required=all(
                        (app_row.profile_id, cid) in completed_pairs for cid in required
                    ),
                )
            )

    out = []
    for posting in postings:
        missing: list[CourseRef] = []
        can_apply = False
        if (
            profile is not None
            and posting.status == "open"
            and profile.status == "active"
            and profile.position_id == posting.position_id
            and posting.id not in my_apps
        ):
            missing = await _missing_courses(db, posting, profile.id)
            can_apply = not missing
        out.append(
            PostingView(
                id=posting.id,
                store_id=posting.store_id,
                store_name=store_names.get(posting.store_id),
                position_id=posting.position_id,
                position_name=position_names.get(posting.position_id),
                starts_at=posting.starts_at,
                ends_at=posting.ends_at,
                pay_note=posting.pay_note,
                note=posting.note,
                required_course_ids=list(posting.required_course_ids or []),
                required_course_titles=[
                    course_titles.get(cid, "курс")
                    for cid in posting.required_course_ids or []
                ],
                auto_confirm=posting.auto_confirm,
                status=posting.status,
                assigned_profile_id=posting.assigned_profile_id,
                assigned_name=assigned_names.get(posting.assigned_profile_id),
                created_at=posting.created_at,
                my_application_status=my_apps.get(posting.id),
                can_apply=can_apply,
                missing_courses=[m.title for m in missing],
                missing=missing,
                applications=all_apps.get(posting.id) if include_applications else None,
            )
        )
    return out


# ─── Менеджер ────────────────────────────────────────────────────────────────


@router.post("/learn/shifts", response_model=PostingView, status_code=201)
async def create_posting(
    body: PostingCreate,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> PostingView:
    store_ids = await _manager_store_ids(db, principal)
    if store_ids is not None and body.store_id not in store_ids:
        raise HTTPException(status_code=403, detail="Не ваш магазин")
    if body.ends_at <= body.starts_at:
        raise HTTPException(status_code=422, detail="Конец смены раньше начала")

    posting = ShiftPosting(
        tenant_id=principal.tenant_id,
        store_id=body.store_id,
        position_id=body.position_id,
        starts_at=body.starts_at,
        ends_at=body.ends_at,
        pay_note=body.pay_note,
        note=body.note,
        required_course_ids=body.required_course_ids,
        auto_confirm=body.auto_confirm,
        created_by=principal.employee_id,
    )
    db.add(posting)
    await db.flush()
    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor_id=principal.employee_id,
        action="create",
        object_type="shift_posting",
        object_id=posting.id,
    )

    # Уведомляем подходящих по должности (батч).
    candidates = [
        r[0]
        for r in await db.execute(
            select(EmployeeProfile.id).where(
                EmployeeProfile.status == "active",
                EmployeeProfile.position_id == posting.position_id,
                EmployeeProfile.employee_id.is_not(None),
            )
        )
    ]
    store_name = (
        await db.execute(select(Store.name).where(Store.id == posting.store_id))
    ).scalar_one_or_none()
    await _notify_profiles(
        db,
        posting,
        candidates,
        kind="shift.new",
        title="Открыта смена на бирже",
        body=f"{store_name or 'Магазин'} · {_fmt_when(posting)} — можно откликнуться.",
    )
    await db.commit()
    await db.refresh(posting)
    profile = await get_profile(db, principal)
    return (await _render_postings(db, [posting], profile=profile, include_applications=True))[0]


@router.post("/learn/shifts/{posting_id}/cancel", status_code=204)
async def cancel_posting(
    posting_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> None:
    posting = await _get_posting_or_404(db, posting_id)
    await _require_posting_manager(db, principal, posting)
    if posting.status not in ("open", "assigned"):
        raise HTTPException(status_code=409, detail="Смена уже закрыта")
    posting.status = "cancelled"
    participant_ids = [
        r[0]
        for r in await db.execute(
            select(ShiftApplication.profile_id).where(
                ShiftApplication.posting_id == posting.id,
                ShiftApplication.status.in_(["pending", "accepted"]),
            )
        )
    ]
    await _notify_profiles(
        db,
        posting,
        participant_ids,
        kind="shift.result",
        title="Смена отменена",
        body=f"Смена {_fmt_when(posting)} отменена магазином.",
    )
    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor_id=principal.employee_id,
        action="update",
        object_type="shift_posting",
        object_id=posting.id,
        diff={"status": {"old": "open", "new": "cancelled"}},
    )
    await db.commit()


@router.post("/learn/shifts/{posting_id}/complete", status_code=204)
async def complete_posting(
    posting_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> None:
    posting = await _get_posting_or_404(db, posting_id)
    await _require_posting_manager(db, principal, posting)
    if posting.status != "assigned":
        raise HTTPException(status_code=409, detail="Завершить можно назначенную смену")
    posting.status = "done"
    await db.commit()


@router.post("/learn/shift-applications/{application_id}/accept", status_code=204)
async def accept_application(
    application_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> None:
    application = await db.get(ShiftApplication, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Отклик не найден")
    posting = await _get_posting_or_404(db, application.posting_id)
    await _require_posting_manager(db, principal, posting)
    if posting.status != "open" or application.status != "pending":
        raise HTTPException(status_code=409, detail="Отклик уже обработан")
    await _assign(db, posting, application)
    await db.commit()


async def _assign(
    db: AsyncSession, posting: ShiftPosting, application: ShiftApplication
) -> None:
    now = datetime.now(UTC)
    application.status = "accepted"
    application.decided_at = now
    posting.status = "assigned"
    posting.assigned_profile_id = application.profile_id

    others = (
        (
            await db.execute(
                select(ShiftApplication).where(
                    ShiftApplication.posting_id == posting.id,
                    ShiftApplication.id != application.id,
                    ShiftApplication.status == "pending",
                )
            )
        )
        .scalars()
        .all()
    )
    for other in others:
        other.status = "declined"
        other.decided_at = now

    await _notify_profiles(
        db,
        posting,
        [application.profile_id],
        kind="shift.result",
        title="Смена ваша!",
        body=f"Вы назначены на смену {_fmt_when(posting)}.",
    )
    if others:
        await _notify_profiles(
            db,
            posting,
            [o.profile_id for o in others],
            kind="shift.result",
            title="Смена занята",
            body=f"На смену {_fmt_when(posting)} выбрали другого сотрудника.",
        )


@router.patch("/learn/shifts/{posting_id}", response_model=PostingView)
async def update_posting(
    posting_id: UUID,
    body: PostingUpdate,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> PostingView:
    posting = await _get_posting_or_404(db, posting_id)
    await _require_posting_manager(db, principal, posting)
    if posting.status != "open":
        raise HTTPException(status_code=409, detail="Изменить можно только открытую смену")
    data = body.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=422, detail="Нечего менять")
    starts_at = data.get("starts_at", posting.starts_at)
    ends_at = data.get("ends_at", posting.ends_at)
    if ends_at <= starts_at:
        raise HTTPException(status_code=422, detail="Конец смены раньше начала")
    diff: dict[str, dict[str, object]] = {}
    for key, value in data.items():
        old_value = getattr(posting, key)
        if old_value != value:
            diff[key] = {"old": str(old_value), "new": str(value)}
            setattr(posting, key, value)
    if diff:
        audit.record(
            db,
            tenant_id=principal.tenant_id,
            actor_id=principal.employee_id,
            action="update",
            object_type="shift_posting",
            object_id=posting.id,
            diff=diff,
        )
    await db.commit()
    await db.refresh(posting)
    profile = await get_profile(db, principal)
    return (await _render_postings(db, [posting], profile=profile, include_applications=True))[0]


@router.post("/learn/shift-applications/{application_id}/decline", status_code=204)
async def decline_application(
    application_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Менеджер отклоняет ОДИН отклик; смена остаётся открытой (в отличие от
    accept, который отклоняет остальных сам)."""
    application = await db.get(ShiftApplication, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Отклик не найден")
    posting = await _get_posting_or_404(db, application.posting_id)
    await _require_posting_manager(db, principal, posting)
    if application.status != "pending":
        raise HTTPException(status_code=409, detail="Отклик уже обработан")
    application.status = "declined"
    application.decided_at = datetime.now(UTC)
    await _notify_profiles(
        db,
        posting,
        [application.profile_id],
        kind="shift.result",
        title="Отклик отклонён",
        body=f"На смену {_fmt_when(posting)} выбрали другого сотрудника.",
    )
    await db.commit()


# ─── Сотрудник ───────────────────────────────────────────────────────────────


@router.post("/learn/shifts/{posting_id}/apply", status_code=204)
async def apply(
    posting_id: UUID,
    body: ApplyBody,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> None:
    await enforce_rate_limit(
        bucket="shift:apply",
        employee_id=str(principal.employee_id),
        limit=30,
        window_sec=60,
    )
    posting = await _get_posting_or_404(db, posting_id)
    profile = await get_profile(db, principal)
    if profile is None or profile.status != "active":
        raise HTTPException(status_code=403, detail="Профиль не активен")
    if posting.status != "open":
        raise HTTPException(status_code=409, detail="Смена уже занята или закрыта")
    if profile.position_id != posting.position_id:
        raise HTTPException(
            status_code=403, detail="Смена для другой должности"
        )
    missing = await _missing_courses(db, posting, profile.id)
    if missing:
        raise HTTPException(
            status_code=409,
            detail="Сначала завершите обучение: " + ", ".join(m.title for m in missing),
        )
    existing = (
        await db.execute(
            select(ShiftApplication).where(
                ShiftApplication.posting_id == posting.id,
                ShiftApplication.profile_id == profile.id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None and existing.status != "withdrawn":
        raise HTTPException(status_code=409, detail="Вы уже откликнулись")

    if existing is not None:
        existing.status = "pending"
        existing.comment = body.comment
        existing.decided_at = None
        application = existing
    else:
        application = ShiftApplication(
            tenant_id=posting.tenant_id,
            posting_id=posting.id,
            profile_id=profile.id,
            comment=body.comment,
        )
        db.add(application)
        await db.flush()

    if posting.auto_confirm:
        await _assign(db, posting, application)
    elif posting.created_by is not None:
        await notify_many(
            db,
            tenant_id=posting.tenant_id,
            employee_ids=[posting.created_by],
            kind="shift.application",
            title="Новый отклик на смену",
            body=f"Отклик на смену {_fmt_when(posting)}: {profile.full_name}.",
            url="/learn/shifts",
            payload={"posting_id": str(posting.id)},
        )
    await db.commit()


@router.post("/learn/shifts/{posting_id}/withdraw", status_code=204)
async def withdraw(
    posting_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> None:
    profile = await get_profile(db, principal)
    if profile is None:
        raise HTTPException(status_code=404, detail="Профиль не найден")
    application = (
        await db.execute(
            select(ShiftApplication).where(
                ShiftApplication.posting_id == posting_id,
                ShiftApplication.profile_id == profile.id,
            )
        )
    ).scalar_one_or_none()
    if application is None or application.status not in ("pending", "accepted"):
        raise HTTPException(status_code=409, detail="Нечего отзывать")

    posting = await _get_posting_or_404(db, posting_id)
    was_accepted = application.status == "accepted"
    application.status = "withdrawn"
    application.decided_at = datetime.now(UTC)
    if was_accepted and posting.assigned_profile_id == profile.id:
        # Назначенный отказался — смена снова открыта, менеджеру сигнал.
        posting.status = "open"
        posting.assigned_profile_id = None
        if posting.created_by is not None:
            await notify_many(
                db,
                tenant_id=posting.tenant_id,
                employee_ids=[posting.created_by],
                kind="shift.application",
                title="Сотрудник отказался от смены",
                body=f"{profile.full_name} снял(а) отклик — смена снова открыта.",
                url="/learn/shifts",
                payload={"posting_id": str(posting.id)},
            )
    await db.commit()

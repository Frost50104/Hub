"""Оргструктура API (Ф0 LMS): справочники + группы + audience dry-run.

Permissions:
- GET /learn/org (снапшот справочников) → любой hub-юзер (нужен пикерам);
- мутации справочников/групп → hub:admin;
- POST /learn/audiences/dry-run, /learn/audiences/rebuild → hub:admin.

Мутации, влияющие на членство аудиторий (составы групп, франчайзи магазина,
родитель отдела), заканчиваются `rebuild_tenant` — «наследование по
оргструктуре» работает сразу, в той же транзакции (ТЗ §2.1/§18).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from signaris_auth import Principal
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db, require_auth
from app.models.employee_profile import EmployeeProfile
from app.models.org import (
    Department,
    Franchisee,
    FranchiseeGroup,
    FranchiseeGroupMember,
    Position,
    PositionGroup,
    PositionGroupMember,
    Store,
    StoreGroup,
    StoreGroupMember,
    UserGroup,
    UserGroupMember,
)
from app.schemas.org import (
    AudienceDryRunBody,
    AudienceDryRunResponse,
    DepartmentCreate,
    DepartmentResponse,
    DepartmentUpdate,
    DryRunProfile,
    GroupMembersReplace,
    GroupResponse,
    OrgSnapshotResponse,
    RefCreate,
    RefResponse,
    RefUpdate,
    StoreCreate,
    StoreResponse,
    StoreUpdate,
)
from app.services import audit
from app.services.audience_resolver import (
    RuleSpec,
    dry_run,
    rebuild_tenant,
    validate_rules,
)
from app.services.learn_notify import notify_new_audience_members

router = APIRouter(tags=["learn-org"])

_ADMIN = require_auth(roles=["admin"])


async def _load_groups(
    db: AsyncSession,
    group_model: type,
    member_model: type,
    member_field: str,
) -> list[GroupResponse]:
    groups = (await db.execute(select(group_model))).scalars().all()
    members: dict[UUID, list[UUID]] = {}
    for group_id, member_id in await db.execute(
        select(member_model.group_id, getattr(member_model, member_field))
    ):
        members.setdefault(group_id, []).append(member_id)
    return [
        GroupResponse(
            id=g.id,
            name=g.name,
            description=getattr(g, "description", None),
            member_ids=members.get(g.id, []),
        )
        for g in sorted(groups, key=lambda x: x.name)
    ]


@router.get("/learn/org", response_model=OrgSnapshotResponse)
async def org_snapshot(
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> OrgSnapshotResponse:
    positions = (await db.execute(select(Position).order_by(Position.name))).scalars().all()
    stores = (await db.execute(select(Store).order_by(Store.name))).scalars().all()
    franchisees = (
        (await db.execute(select(Franchisee).order_by(Franchisee.name))).scalars().all()
    )
    departments = (
        (await db.execute(select(Department).order_by(Department.name))).scalars().all()
    )
    return OrgSnapshotResponse(
        positions=[RefResponse.model_validate(x) for x in positions],
        position_groups=await _load_groups(
            db, PositionGroup, PositionGroupMember, "position_id"
        ),
        stores=[StoreResponse.model_validate(x) for x in stores],
        store_groups=await _load_groups(db, StoreGroup, StoreGroupMember, "store_id"),
        franchisees=[RefResponse.model_validate(x) for x in franchisees],
        franchisee_groups=await _load_groups(
            db, FranchiseeGroup, FranchiseeGroupMember, "franchisee_id"
        ),
        departments=[DepartmentResponse.model_validate(x) for x in departments],
        user_groups=await _load_groups(db, UserGroup, UserGroupMember, "profile_id"),
    )


# --- Простые архивируемые справочники (positions / franchisees) -------------


async def _create_ref(
    db: AsyncSession, principal: Principal, model: type, body: RefCreate, object_type: str
):
    row = model(tenant_id=principal.tenant_id, name=body.name)
    if hasattr(row, "description"):
        row.description = body.description
    elif hasattr(row, "contact_info"):
        row.contact_info = body.description
    db.add(row)
    try:
        await db.flush()
    except IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"«{body.name}» уже существует",
        ) from None
    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor_id=principal.employee_id,
        action="create",
        object_type=object_type,
        object_id=row.id,
        object_label=row.name,
    )
    await db.commit()
    await db.refresh(row)
    return row


async def _update_ref(
    db: AsyncSession,
    principal: Principal,
    model: type,
    ref_id: UUID,
    body: RefUpdate,
    object_type: str,
):
    row = await db.get(model, ref_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Не найдено")
    diff: dict[str, Any] = {}
    if body.name is not None and body.name != row.name:
        diff["name"] = {"old": row.name, "new": body.name}
        row.name = body.name
    if body.description is not None:
        target = "description" if hasattr(row, "description") else "contact_info"
        setattr(row, target, body.description)
    if body.archived is not None:
        was = row.archived_at is not None
        if body.archived != was:
            diff["archived"] = {"old": was, "new": body.archived}
            row.archived_at = func.now() if body.archived else None
    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor_id=principal.employee_id,
        action="update",
        object_type=object_type,
        object_id=row.id,
        object_label=row.name,
        diff=diff or None,
    )
    await db.commit()
    await db.refresh(row)
    return row


async def _delete_ref(
    db: AsyncSession,
    principal: Principal,
    model: type,
    ref_id: UUID,
    object_type: str,
    *,
    in_use: bool,
) -> None:
    row = await db.get(model, ref_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Не найдено")
    if in_use:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="На запись ссылаются сотрудники — архивируйте её вместо удаления",
        )
    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor_id=principal.employee_id,
        action="delete",
        object_type=object_type,
        object_id=row.id,
        object_label=row.name,
    )
    await db.delete(row)
    diffs = await rebuild_tenant(db, principal.tenant_id)
    await notify_new_audience_members(db, diffs)
    await db.commit()


async def _profiles_use(db: AsyncSession, column, ref_id: UUID) -> bool:  # noqa: ANN001
    return (
        await db.execute(select(EmployeeProfile.id).where(column == ref_id).limit(1))
    ).scalar_one_or_none() is not None


@router.post("/learn/org/positions", response_model=RefResponse, status_code=201)
async def create_position(
    body: RefCreate,
    principal: Principal = Depends(_ADMIN),
    db: AsyncSession = Depends(get_db),
) -> RefResponse:
    return RefResponse.model_validate(
        await _create_ref(db, principal, Position, body, "position")
    )


@router.patch("/learn/org/positions/{ref_id}", response_model=RefResponse)
async def update_position(
    ref_id: UUID,
    body: RefUpdate,
    principal: Principal = Depends(_ADMIN),
    db: AsyncSession = Depends(get_db),
) -> RefResponse:
    return RefResponse.model_validate(
        await _update_ref(db, principal, Position, ref_id, body, "position")
    )


@router.delete("/learn/org/positions/{ref_id}", status_code=204)
async def delete_position(
    ref_id: UUID,
    principal: Principal = Depends(_ADMIN),
    db: AsyncSession = Depends(get_db),
) -> None:
    in_use = await _profiles_use(db, EmployeeProfile.position_id, ref_id)
    await _delete_ref(db, principal, Position, ref_id, "position", in_use=in_use)


@router.post("/learn/org/franchisees", response_model=RefResponse, status_code=201)
async def create_franchisee(
    body: RefCreate,
    principal: Principal = Depends(_ADMIN),
    db: AsyncSession = Depends(get_db),
) -> RefResponse:
    row = await _create_ref(db, principal, Franchisee, body, "franchisee")
    return RefResponse(
        id=row.id, name=row.name, description=row.contact_info, archived_at=row.archived_at
    )


@router.patch("/learn/org/franchisees/{ref_id}", response_model=RefResponse)
async def update_franchisee(
    ref_id: UUID,
    body: RefUpdate,
    principal: Principal = Depends(_ADMIN),
    db: AsyncSession = Depends(get_db),
) -> RefResponse:
    row = await _update_ref(db, principal, Franchisee, ref_id, body, "franchisee")
    return RefResponse(
        id=row.id, name=row.name, description=row.contact_info, archived_at=row.archived_at
    )


@router.delete("/learn/org/franchisees/{ref_id}", status_code=204)
async def delete_franchisee(
    ref_id: UUID,
    principal: Principal = Depends(_ADMIN),
    db: AsyncSession = Depends(get_db),
) -> None:
    in_use = await _profiles_use(db, EmployeeProfile.franchisee_id, ref_id) or (
        (
            await db.execute(select(Store.id).where(Store.franchisee_id == ref_id).limit(1))
        ).scalar_one_or_none()
        is not None
    )
    await _delete_ref(db, principal, Franchisee, ref_id, "franchisee", in_use=in_use)


# --- Магазины ----------------------------------------------------------------


@router.post("/learn/org/stores", response_model=StoreResponse, status_code=201)
async def create_store(
    body: StoreCreate,
    principal: Principal = Depends(_ADMIN),
    db: AsyncSession = Depends(get_db),
) -> StoreResponse:
    store = Store(
        tenant_id=principal.tenant_id,
        name=body.name,
        code=body.code,
        address=body.address,
        franchisee_id=body.franchisee_id,
    )
    db.add(store)
    try:
        await db.flush()
    except IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"«{body.name}» уже существует"
        ) from None
    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor_id=principal.employee_id,
        action="create",
        object_type="store",
        object_id=store.id,
        object_label=store.name,
    )
    await db.commit()
    await db.refresh(store)
    return StoreResponse.model_validate(store)


@router.patch("/learn/org/stores/{ref_id}", response_model=StoreResponse)
async def update_store(
    ref_id: UUID,
    body: StoreUpdate,
    principal: Principal = Depends(_ADMIN),
    db: AsyncSession = Depends(get_db),
) -> StoreResponse:
    store = await db.get(Store, ref_id)
    if store is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Магазин не найден")
    fields = body.model_dump(exclude_unset=True)
    diff = {}
    franchisee_changed = False
    for name, value in fields.items():
        if name == "archived":
            was = store.archived_at is not None
            if value != was:
                diff["archived"] = {"old": was, "new": value}
                store.archived_at = func.now() if value else None
            continue
        old = getattr(store, name)
        if old != value:
            diff[name] = {"old": str(old) if old else None, "new": str(value) if value else None}
            setattr(store, name, value)
            if name == "franchisee_id":
                franchisee_changed = True
    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor_id=principal.employee_id,
        action="update",
        object_type="store",
        object_id=store.id,
        object_label=store.name,
        diff=diff or None,
    )
    if franchisee_changed or "archived" in diff:
        # Франчайзи магазина участвует в атрибутах его сотрудников.
        diffs = await rebuild_tenant(db, principal.tenant_id)
        await notify_new_audience_members(db, diffs)
    await db.commit()
    await db.refresh(store)
    return StoreResponse.model_validate(store)


@router.delete("/learn/org/stores/{ref_id}", status_code=204)
async def delete_store(
    ref_id: UUID,
    principal: Principal = Depends(_ADMIN),
    db: AsyncSession = Depends(get_db),
) -> None:
    in_use = await _profiles_use(db, EmployeeProfile.store_id, ref_id)
    await _delete_ref(db, principal, Store, ref_id, "store", in_use=in_use)


# --- Отделы -------------------------------------------------------------------


@router.post("/learn/org/departments", response_model=DepartmentResponse, status_code=201)
async def create_department(
    body: DepartmentCreate,
    principal: Principal = Depends(_ADMIN),
    db: AsyncSession = Depends(get_db),
) -> DepartmentResponse:
    dep = Department(tenant_id=principal.tenant_id, name=body.name, parent_id=body.parent_id)
    db.add(dep)
    await db.flush()
    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor_id=principal.employee_id,
        action="create",
        object_type="department",
        object_id=dep.id,
        object_label=dep.name,
    )
    await db.commit()
    await db.refresh(dep)
    return DepartmentResponse.model_validate(dep)


@router.patch("/learn/org/departments/{ref_id}", response_model=DepartmentResponse)
async def update_department(
    ref_id: UUID,
    body: DepartmentUpdate,
    principal: Principal = Depends(_ADMIN),
    db: AsyncSession = Depends(get_db),
) -> DepartmentResponse:
    dep = await db.get(Department, ref_id)
    if dep is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Отдел не найден")
    if body.parent_id == ref_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Отдел не может быть родителем самого себя",
        )
    fields = body.model_dump(exclude_unset=True)
    parent_changed = "parent_id" in fields and fields["parent_id"] != dep.parent_id
    for name, value in fields.items():
        setattr(dep, name, value)
    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor_id=principal.employee_id,
        action="update",
        object_type="department",
        object_id=dep.id,
        object_label=dep.name,
    )
    if parent_changed:
        # Правило «отделу X» матчит и под-отделы — иерархия влияет на членство.
        diffs = await rebuild_tenant(db, principal.tenant_id)
        await notify_new_audience_members(db, diffs)
    await db.commit()
    await db.refresh(dep)
    return DepartmentResponse.model_validate(dep)


@router.delete("/learn/org/departments/{ref_id}", status_code=204)
async def delete_department(
    ref_id: UUID,
    principal: Principal = Depends(_ADMIN),
    db: AsyncSession = Depends(get_db),
) -> None:
    has_children = (
        await db.execute(select(Department.id).where(Department.parent_id == ref_id).limit(1))
    ).scalar_one_or_none() is not None
    in_use = await _profiles_use(db, EmployeeProfile.department_id, ref_id) or has_children
    await _delete_ref(db, principal, Department, ref_id, "department", in_use=in_use)


# --- Группы (общий паттерн: CRUD + replace members) ---------------------------

_GROUP_KINDS: dict[str, tuple[type, type, str, str]] = {
    "position-groups": (PositionGroup, PositionGroupMember, "position_id", "position_group"),
    "store-groups": (StoreGroup, StoreGroupMember, "store_id", "store_group"),
    "franchisee-groups": (
        FranchiseeGroup,
        FranchiseeGroupMember,
        "franchisee_id",
        "franchisee_group",
    ),
    "user-groups": (UserGroup, UserGroupMember, "profile_id", "user_group"),
}


def _group_kind(kind: str) -> tuple[type, type, str, str]:
    if kind not in _GROUP_KINDS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Не найдено")
    return _GROUP_KINDS[kind]


@router.post("/learn/org/{kind}", response_model=GroupResponse, status_code=201)
async def create_group(
    kind: str,
    body: RefCreate,
    principal: Principal = Depends(_ADMIN),
    db: AsyncSession = Depends(get_db),
) -> GroupResponse:
    group_model, _, _, object_type = _group_kind(kind)
    group = group_model(tenant_id=principal.tenant_id, name=body.name)
    if hasattr(group, "description"):
        group.description = body.description
    db.add(group)
    await db.flush()
    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor_id=principal.employee_id,
        action="create",
        object_type=object_type,
        object_id=group.id,
        object_label=group.name,
    )
    await db.commit()
    return GroupResponse(
        id=group.id,
        name=group.name,
        description=getattr(group, "description", None),
        member_ids=[],
    )


@router.patch("/learn/org/{kind}/{group_id}", response_model=GroupResponse)
async def rename_group(
    kind: str,
    group_id: UUID,
    body: RefUpdate,
    principal: Principal = Depends(_ADMIN),
    db: AsyncSession = Depends(get_db),
) -> GroupResponse:
    group_model, member_model, member_field, object_type = _group_kind(kind)
    group = await db.get(group_model, group_id)
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Группа не найдена")
    if body.name is not None:
        group.name = body.name
    if body.description is not None and hasattr(group, "description"):
        group.description = body.description
    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor_id=principal.employee_id,
        action="update",
        object_type=object_type,
        object_id=group.id,
        object_label=group.name,
    )
    await db.commit()
    member_ids = [
        r[0]
        for r in await db.execute(
            select(getattr(member_model, member_field)).where(
                member_model.group_id == group_id
            )
        )
    ]
    return GroupResponse(
        id=group.id,
        name=group.name,
        description=getattr(group, "description", None),
        member_ids=member_ids,
    )


@router.put("/learn/org/{kind}/{group_id}/members", response_model=GroupResponse)
async def replace_group_members(
    kind: str,
    group_id: UUID,
    body: GroupMembersReplace,
    principal: Principal = Depends(_ADMIN),
    db: AsyncSession = Depends(get_db),
) -> GroupResponse:
    group_model, member_model, member_field, object_type = _group_kind(kind)
    group = await db.get(group_model, group_id)
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Группа не найдена")
    await db.execute(delete(member_model).where(member_model.group_id == group_id))
    unique_ids = list(dict.fromkeys(body.member_ids))
    for member_id in unique_ids:
        db.add(
            member_model(
                tenant_id=principal.tenant_id,
                group_id=group_id,
                **{member_field: member_id},
            )
        )
    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor_id=principal.employee_id,
        action="access_change",
        object_type=object_type,
        object_id=group.id,
        object_label=group.name,
        diff={"members_count": {"old": None, "new": len(unique_ids)}},
    )
    # Состав группы — измерение audience-правил.
    diffs = await rebuild_tenant(db, principal.tenant_id)
    await notify_new_audience_members(db, diffs)
    await db.commit()
    return GroupResponse(
        id=group.id,
        name=group.name,
        description=getattr(group, "description", None),
        member_ids=unique_ids,
    )


@router.delete("/learn/org/{kind}/{group_id}", status_code=204)
async def delete_group(
    kind: str,
    group_id: UUID,
    principal: Principal = Depends(_ADMIN),
    db: AsyncSession = Depends(get_db),
) -> None:
    group_model, _, _, object_type = _group_kind(kind)
    group = await db.get(group_model, group_id)
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Группа не найдена")
    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor_id=principal.employee_id,
        action="delete",
        object_type=object_type,
        object_id=group.id,
        object_label=group.name,
    )
    await db.delete(group)
    diffs = await rebuild_tenant(db, principal.tenant_id)
    await notify_new_audience_members(db, diffs)
    await db.commit()


# --- Audience dry-run + пересчёт ----------------------------------------------


def _rule_specs(body: AudienceDryRunBody) -> list[RuleSpec]:
    return [
        RuleSpec(
            mode=r.mode,
            profile_ids=frozenset(r.profile_ids),
            position_ids=frozenset(r.position_ids),
            position_group_ids=frozenset(r.position_group_ids),
            store_ids=frozenset(r.store_ids),
            store_group_ids=frozenset(r.store_group_ids),
            franchisee_ids=frozenset(r.franchisee_ids),
            franchisee_group_ids=frozenset(r.franchisee_group_ids),
            department_ids=frozenset(r.department_ids),
            user_group_ids=frozenset(r.user_group_ids),
        )
        for r in body.rules
    ]


@router.post("/learn/audiences/dry-run", response_model=AudienceDryRunResponse)
async def audience_dry_run(
    body: AudienceDryRunBody,
    principal: Principal = Depends(_ADMIN),
    db: AsyncSession = Depends(get_db),
) -> AudienceDryRunResponse:
    try:
        specs = _rule_specs(body)
        validate_rules(specs)
        count, sample_ids = await dry_run(db, is_all=body.is_all, rules=specs)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)
        ) from None
    names = {
        row[0]: row[1]
        for row in await db.execute(
            select(EmployeeProfile.id, EmployeeProfile.full_name).where(
                EmployeeProfile.id.in_(sample_ids)
            )
        )
    }
    return AudienceDryRunResponse(
        count=count,
        sample=[
            DryRunProfile(id=pid, full_name=names.get(pid, "?")) for pid in sample_ids
        ],
    )


@router.post("/learn/audiences/rebuild")
async def audience_rebuild(
    principal: Principal = Depends(_ADMIN),
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    """Админ-кнопка «пересчитать доступы» (страховка от рассинхрона)."""
    diffs = await rebuild_tenant(db, principal.tenant_id)
    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor_id=principal.employee_id,
        action="access_change",
        object_type="audience",
        object_label="полный пересчёт",
        diff={"audiences_changed": {"old": None, "new": len(diffs)}},
    )
    await db.commit()
    return {"audiences_changed": len(diffs)}

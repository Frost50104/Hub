"""Tenant-wide endpoints: member autocomplete for @mentions etc.

`shadow_users` is RLS-scoped to the current tenant, so a raw SELECT (without
explicit `WHERE tenant_id = ...`) returns only the right set.

Правила поиска (пословно, ё→е, ранжирование) живут в
`app/services/people_search.py` — та же функция обслуживает экран
«Сотрудники». Поле `mention` считает СЕРВЕР: клиент вставляет его в текст
дословно и сам решение «имя или логин» не принимает.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from signaris_auth import Principal
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db, require_auth
from app.models.shadow import ShadowUser
from app.schemas.tenant import TenantMemberBrief
from app.services.people_search import (
    match_condition,
    mention_token_expr,
    normalized_col,
    rank_expr,
)

router = APIRouter(tags=["tenant"])


@router.get("/tenant/members", response_model=list[TenantMemberBrief])
async def list_tenant_members(
    q: str | None = Query(default=None, max_length=128),
    limit: int = Query(default=10, ge=1, le=50),
    # Справочник сотрудников (email, ФИО) — только пользователям Hub,
    # а не любому валидному Signaris-JWT.
    _principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> list[TenantMemberBrief]:
    # Тёзок считаем ДО фильтра и лимита: уникальность имени — свойство всего
    # справочника, а не текущей выдачи. Иначе «Иван Петров» получил бы
    # токен-имя только потому, что его двойник не подошёл под запрос.
    base = (
        select(
            ShadowUser.employee_id,
            ShadowUser.email,
            ShadowUser.full_name,
            func.count()
            .over(partition_by=normalized_col(ShadowUser.full_name))
            .label("twins"),
        )
        .where(ShadowUser.deleted_at.is_(None))
        .subquery()
    )
    stmt = (
        select(
            base.c.employee_id,
            base.c.email,
            base.c.full_name,
            mention_token_expr(base.c.full_name, base.c.email, base.c.twins).label(
                "mention"
            ),
        )
        .order_by(rank_expr(base.c.full_name, base.c.email, q), base.c.full_name)
        .limit(limit)
    )
    cond = match_condition(base.c.full_name, base.c.email, q)
    if cond is not None:
        stmt = stmt.where(cond)
    rows = (await db.execute(stmt)).all()
    return [
        TenantMemberBrief(
            employee_id=r.employee_id,
            email=r.email,
            full_name=r.full_name,
            handle=r.email.split("@", 1)[0].lower(),
            mention=r.mention,
        )
        for r in rows
    ]

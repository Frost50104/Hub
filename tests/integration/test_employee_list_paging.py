"""Потолок в 100 записей на «Управление → Сотрудники» (31.08).

ОС владельца: «показываются не все сотрудники». На проде активных профилей было
149, а экран рисовал 100 — `useEmployees` жёстко слал `limit: 100`, и рядом
честно стояло «Всего: 149». Клиент теперь добирает набор СТРАНИЦАМИ, и от ручки
это требует двух вещей, которых с ней раньше никто не спрашивал: честного
`total` при обрезанной выдаче и УСТОЙЧИВОГО порядка между страницами.

Ручка до этого не была покрыта тестами вовсе.

Общий приём: профили заводятся с уникальным префиксом в имени и email, а
выборка сужается тем же префиксом через `q`. Тесты, коммитящие через ручки,
делят один тенант, и без сужения `total` считал бы чужие профили.
"""

from __future__ import annotations

import inspect
import uuid

import pytest
from annotated_types import Le
from signaris_auth.shadow import upsert_shadow_tenant, upsert_shadow_user
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.employees import list_employees
from app.models.employee_profile import EmployeeProfile, TuStoreAssignment
from app.models.org import Store
from tests.integration.conftest import make_principal

pytestmark = pytest.mark.integration


async def _admin(db: AsyncSession, tenant_id: uuid.UUID, slug: str):
    principal = make_principal(
        tenant_id, email=f"adm-{slug}@t.ru", role="admin", tenant_slug=slug
    )
    await upsert_shadow_tenant(db, principal, table="shadow_tenants")
    await upsert_shadow_user(db, principal, table="shadow_users")
    return principal


async def _bulk(
    db: AsyncSession, tenant_id: uuid.UUID, prefix: str, n: int, *, same_name: bool = False
) -> None:
    for i in range(n):
        db.add(
            EmployeeProfile(
                tenant_id=tenant_id,
                email=f"{prefix}-{i:03d}@t.ru",
                full_name=prefix if same_name else f"{prefix}-{i:03d}",
            )
        )
    await db.flush()


async def _page(principal, db: AsyncSession, prefix: str, *, limit: int, offset: int):
    return await list_employees(
        status_filter="active",
        q=prefix,
        store_id=None,
        position_id=None,
        limit=limit,
        offset=offset,
        principal=principal,
        db=db,
    )


async def test_total_is_honest_while_items_are_capped(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Ровно та развилка, из-за которой экран себе противоречил.

    `total` обязан считать ВСЮ выборку, а не отданную страницу: на нём держится
    и подпись «Показаны N из M», и условие останова постраничного добора.
    """
    admin = await _admin(db, tenant_id, "ep1")
    await _bulk(db, tenant_id, "ep1x", 150)

    res = await _page(admin, db, "ep1x", limit=100, offset=0)
    assert res.total == 150
    assert len(res.items) == 100


async def test_paging_returns_every_profile_exactly_once(
    db: AsyncSession, tenant_id: uuid.UUID
):
    admin = await _admin(db, tenant_id, "ep2")
    await _bulk(db, tenant_id, "ep2x", 150)

    seen: list[uuid.UUID] = []
    offset = 0
    while True:
        page = await _page(admin, db, "ep2x", limit=50, offset=offset)
        seen.extend(p.id for p in page.items)
        if len(page.items) < 50:
            break
        offset += 50

    assert len(seen) == 150
    assert len(set(seen)) == 150, "страницы пересеклись — порядок неустойчив"


async def test_full_namesakes_do_not_break_the_page_boundary(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Полные тёзки — единственный случай, где сортировки по `full_name` не
    хватает: порядок внутри группы одинаковых имён ничем не задан, и стык
    страниц может повторить одного и потерять другого. Тай-брейкер по `id`
    делает порядок полным.
    """
    admin = await _admin(db, tenant_id, "ep3")
    await _bulk(db, tenant_id, "ep3x", 20, same_name=True)

    seen: list[uuid.UUID] = []
    for offset in range(0, 20, 3):
        page = await _page(admin, db, "ep3x", limit=3, offset=offset)
        seen.extend(p.id for p in page.items)

    assert len(set(seen)) == 20, "тёзки размножились или потерялись на стыке"


def test_page_size_cap_is_declared():
    """Клиент ходит с `limit=500` — ровно потолком ручки. Если потолок опустят,
    добор молча начнёт терять людей, а если снимут — один запрос сможет вытащить
    весь тенант.

    Проверяем ОБЪЯВЛЕНИЕ, а не отказ на 501: ограничения `Query` применяет
    FastAPI при разборе HTTP-запроса, а интеграционные тесты зовут функции
    ручек напрямую и валидацию параметров не проходят вовсе. Тест на «501 →
    422» здесь был бы зелёным ровно до первого настоящего запроса.
    """
    limit = inspect.signature(list_employees).parameters["limit"].default
    assert limit.default == 100
    assert Le(500) in limit.metadata


async def test_total_respects_the_tu_scope(db: AsyncSession, tenant_id: uuid.UUID):
    """`total` считается по той же выборке, что и `items` — включая скоуп.

    Иначе ТУ увидел бы «Показаны 3 из 150» и решил, что от него что-то прячут.
    """
    store = Store(tenant_id=tenant_id, name=f"Точка ep5 {uuid.uuid4().hex[:6]}")
    other = Store(tenant_id=tenant_id, name=f"Точка ep5b {uuid.uuid4().hex[:6]}")
    db.add_all([store, other])
    await db.flush()

    tu_principal = make_principal(
        tenant_id, email="tu-ep5@t.ru", role="member", tenant_slug="ep5"
    )
    await upsert_shadow_tenant(db, tu_principal, table="shadow_tenants")
    await upsert_shadow_user(db, tu_principal, table="shadow_users")
    tu = EmployeeProfile(
        tenant_id=tenant_id,
        employee_id=tu_principal.employee_id,
        email="tu-ep5@t.ru",
        full_name="ep5x-tu",
        org_role="tu",
        store_id=store.id,
    )
    db.add(tu)
    await db.flush()
    db.add(TuStoreAssignment(tenant_id=tenant_id, profile_id=tu.id, store_id=store.id))

    for i, s in enumerate([store, store, other, other]):
        db.add(
            EmployeeProfile(
                tenant_id=tenant_id,
                email=f"ep5x-{i}@t.ru",
                full_name=f"ep5x-{i}",
                store_id=s.id,
            )
        )
    await db.flush()

    res = await _page(tu_principal, db, "ep5x", limit=100, offset=0)
    # Двое своих + сам ТУ; чужая точка не считается ни в items, ни в total.
    assert res.total == 3
    assert len(res.items) == 3

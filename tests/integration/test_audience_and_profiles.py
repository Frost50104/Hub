"""Integration-тесты Ф0: пересчёт audience_members + матчинг профилей (реальный PG).

Закрывают DB-зависимые находки ревью: diff-пересчёт сохраняет granted_at,
перевод сотрудника мгновенно меняет членство, повторный найм не создаёт
дубль, архивация вычищает членства, восстановление возвращает.
"""

from __future__ import annotations

import uuid

import pytest
from signaris_auth.shadow import upsert_shadow_tenant, upsert_shadow_user
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audience import Audience, AudienceMember, AudienceRule
from app.models.employee_profile import EmployeeProfile
from app.models.org import Position, Store
from app.services.audience_resolver import recalc_audience, recalc_profile
from app.services.employee_profiles import (
    archive_profile,
    ensure_profile_for_principal,
    restore_profile,
)
from tests.integration.conftest import make_principal

pytestmark = pytest.mark.integration


async def _mk_profile(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    email: str,
    position_id: uuid.UUID | None = None,
    store_id: uuid.UUID | None = None,
) -> EmployeeProfile:
    profile = EmployeeProfile(
        tenant_id=tenant_id,
        email=email,
        full_name=email.split("@")[0],
        position_id=position_id,
        store_id=store_id,
    )
    db.add(profile)
    await db.flush()
    return profile


async def _members(db: AsyncSession, audience_id: uuid.UUID) -> dict[uuid.UUID, object]:
    rows = await db.execute(
        select(AudienceMember.profile_id, AudienceMember.granted_at).where(
            AudienceMember.audience_id == audience_id
        )
    )
    return {r[0]: r[1] for r in rows}


async def test_recalc_diff_preserves_granted_at(db: AsyncSession, tenant_id: uuid.UUID):
    pos_seller = Position(tenant_id=tenant_id, name="Продавец")
    pos_admin = Position(tenant_id=tenant_id, name="Администратор")
    db.add_all([pos_seller, pos_admin])
    await db.flush()

    seller = await _mk_profile(db, tenant_id, email="s@t.ru", position_id=pos_seller.id)
    admin = await _mk_profile(db, tenant_id, email="a@t.ru", position_id=pos_admin.id)

    audience = Audience(tenant_id=tenant_id)
    db.add(audience)
    await db.flush()
    db.add(
        AudienceRule(
            tenant_id=tenant_id,
            audience_id=audience.id,
            mode="include",
            position_ids=[pos_seller.id],
        )
    )
    await db.flush()

    diff = await recalc_audience(db, audience)
    assert diff.added == [seller.id]
    first = await _members(db, audience.id)
    assert set(first) == {seller.id}

    # Расширяем правило на администраторов: продавец остаётся с ИСХОДНЫМ
    # granted_at (diff/upsert, не truncate).
    db.add(
        AudienceRule(
            tenant_id=tenant_id,
            audience_id=audience.id,
            mode="include",
            position_ids=[pos_admin.id],
        )
    )
    await db.flush()
    diff = await recalc_audience(db, audience)
    assert diff.added == [admin.id] and not diff.removed
    second = await _members(db, audience.id)
    assert second[seller.id] == first[seller.id]
    assert set(second) == {seller.id, admin.id}


async def test_profile_transfer_updates_membership(db: AsyncSession, tenant_id: uuid.UUID):
    store_a = Store(tenant_id=tenant_id, name="П14")
    store_b = Store(tenant_id=tenant_id, name="Л15")
    db.add_all([store_a, store_b])
    await db.flush()
    employee = await _mk_profile(db, tenant_id, email="e@t.ru", store_id=store_a.id)

    audience = Audience(tenant_id=tenant_id)
    db.add(audience)
    await db.flush()
    db.add(
        AudienceRule(
            tenant_id=tenant_id,
            audience_id=audience.id,
            mode="include",
            store_ids=[store_a.id],
        )
    )
    await db.flush()
    await recalc_audience(db, audience)
    assert set(await _members(db, audience.id)) == {employee.id}

    # Перевод в другой магазин: «доступы меняются автоматически» (ТЗ §2.1).
    employee.store_id = store_b.id
    await db.flush()
    await recalc_profile(db, employee)
    assert set(await _members(db, audience.id)) == set()


async def test_matching_link_create_and_rehire(db: AsyncSession, tenant_id: uuid.UUID):
    # Карточка заведена HR заранее (регистр email нарочно другой).
    card = await _mk_profile(db, tenant_id, email="maria.ivanova@uppetit.ru")

    principal = make_principal(tenant_id, email="Maria.Ivanova@UPPETIT.ru")
    await upsert_shadow_tenant(db, principal, table="shadow_tenants")
    await upsert_shadow_user(db, principal, table="shadow_users")

    result = await ensure_profile_for_principal(db, principal)
    assert result.outcome == "linked"
    assert result.profile is not None and result.profile.id == card.id
    assert result.profile.employee_id == principal.employee_id

    # Повторный вход — идемпотентно.
    result = await ensure_profile_for_principal(db, principal)
    assert result.outcome == "already_linked"

    # Неизвестный email → авто-создание минимальной карточки.
    stranger = make_principal(tenant_id, email="new@uppetit.ru", full_name="Новый")
    await upsert_shadow_user(db, stranger, table="shadow_users")
    result = await ensure_profile_for_principal(db, stranger)
    assert result.outcome == "created"
    assert result.profile is not None and result.profile.email == "new@uppetit.ru"

    # Повторный найм: карточка в архиве, у человека НОВЫЙ employee_id —
    # дубль не создаётся, требуется restore.
    await archive_profile(db, card, reason="manual", actor_id=None)
    rehired = make_principal(tenant_id, email="maria.ivanova@uppetit.ru")
    await upsert_shadow_user(db, rehired, table="shadow_users")
    result = await ensure_profile_for_principal(db, rehired)
    assert result.outcome == "needs_restore"
    assert result.profile is not None and result.profile.id == card.id

    # Restore с перепривязкой на новый вход.
    await restore_profile(db, card, actor_id=None, new_employee_id=rehired.employee_id)
    assert card.status == "active" and card.employee_id == rehired.employee_id


async def test_archive_cascade_removes_membership(db: AsyncSession, tenant_id: uuid.UUID):
    # Ассерты по КОНКРЕТНОМУ профилю: testcontainers-юзер — superuser, RLS
    # не изолирует is_all-аудиторию от закоммиченных профилей других тестов.
    employee = await _mk_profile(db, tenant_id, email="x@t.ru")
    audience = Audience(tenant_id=tenant_id, is_all=True)
    db.add(audience)
    await db.flush()
    await recalc_audience(db, audience)
    assert employee.id in set(await _members(db, audience.id))

    await archive_profile(db, employee, reason="manual", actor_id=None)
    assert employee.id not in set(await _members(db, audience.id))

    await restore_profile(db, employee, actor_id=None)
    assert employee.id in set(await _members(db, audience.id))


# --- org_roles («Контур») + GET rules (ОС 2026-08-10) ------------------------


async def test_org_roles_rule_recalc(db: AsyncSession, tenant_id: uuid.UUID):
    office = await _mk_profile(db, tenant_id, email="ofc@t.ru")
    office.org_role = "office"
    seller = await _mk_profile(db, tenant_id, email="sel@t.ru")  # employee по умолчанию
    await db.flush()

    audience = Audience(tenant_id=tenant_id)
    db.add(audience)
    await db.flush()
    db.add(
        AudienceRule(
            tenant_id=tenant_id,
            audience_id=audience.id,
            mode="include",
            org_roles=["office"],
        )
    )
    await db.flush()

    await recalc_audience(db, audience)
    members = set(await _members(db, audience.id))
    assert office.id in members
    assert seller.id not in members


async def test_get_audience_rules_roundtrip(db: AsyncSession, tenant_id: uuid.UUID):
    from fastapi import HTTPException

    from app.api.org import get_audience_rules

    target = await _mk_profile(db, tenant_id, email="tgt@t.ru")
    hr = await _mk_profile(db, tenant_id, email="hr2@t.ru")
    hr.content_role = "publisher"
    await db.flush()

    audience = Audience(tenant_id=tenant_id)
    db.add(audience)
    await db.flush()
    db.add(
        AudienceRule(
            tenant_id=tenant_id,
            audience_id=audience.id,
            mode="include",
            profile_ids=[target.id],
            org_roles=["office", "tu"],
        )
    )
    await db.flush()

    slug = f"t-{tenant_id.hex[:12]}"
    hr_principal = make_principal(tenant_id, email="hr2@t.ru", tenant_slug=slug)
    await upsert_shadow_tenant(db, hr_principal, table="shadow_tenants")
    await upsert_shadow_user(db, hr_principal, table="shadow_users")
    hr.employee_id = hr_principal.employee_id
    await db.flush()

    resp = await get_audience_rules(audience.id, hr_principal, db)
    assert resp.is_all is False
    assert len(resp.rules) == 1
    rule = resp.rules[0]
    assert rule.profile_ids == [target.id]
    assert sorted(rule.org_roles) == ["office", "tu"]
    # Имена для чипов — по всем profile_ids правила.
    assert resp.profile_labels[target.id] == target.full_name

    # Обычный member (без content_role) — 403.
    member_principal = make_principal(tenant_id, email="mm@t.ru", tenant_slug=slug)
    await upsert_shadow_user(db, member_principal, table="shadow_users")
    with pytest.raises(HTTPException) as exc:
        await get_audience_rules(audience.id, member_principal, db)
    assert exc.value.status_code == 403


async def test_dimension_counts_explain_empty_pick(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Счётчики у значений пикера: почему «Увидят: 0» (ОС 2026-08-24).

    Тестировщица выбирала должность «Администратор», получала ноль и не могла
    понять причину — должность просто никому не проставлена. Счётчик обязан
    показывать это ДО сохранения.
    """
    from app.services.audience_resolver import dimension_counts

    seller_pos = Position(tenant_id=tenant_id, name="Продавец-бариста")
    admin_pos = Position(tenant_id=tenant_id, name="Администратор")
    db.add_all([seller_pos, admin_pos])
    await db.flush()

    # Контуры — общий словарь на всю базу, а интеграционные тесты бегут
    # суперпользователем (RLS не действует), поэтому по ним считаем ДЕЛЬТУ.
    # В проде выборку сужает RLS — ровно как у dry-run.
    before = await dimension_counts(db)
    await _mk_profile(db, tenant_id, email="s1@t.ru", position_id=seller_pos.id)
    await _mk_profile(db, tenant_id, email="s2@t.ru", position_id=seller_pos.id)
    office = await _mk_profile(db, tenant_id, email="ofc@t.ru")
    office.org_role = "office"
    await db.flush()

    counts = await dimension_counts(db)
    positions = counts["position_ids"]
    assert positions[str(seller_pos.id)] == 2
    # Должность без людей в ответе ОТСУТСТВУЕТ — клиент рисует ноль сам.
    assert str(admin_pos.id) not in positions

    def delta(role: str) -> int:
        return counts["org_roles"].get(role, 0) - before["org_roles"].get(role, 0)

    assert delta("office") == 1
    assert delta("employee") == 2


async def test_dimension_counts_match_dry_run(db: AsyncSession, tenant_id: uuid.UUID):
    """Число у значения и «Увидят: N» обязаны сходиться на правиле из одного
    измерения: разойдутся — подсказка соврёт прямо в том же окне."""
    from app.services.audience_resolver import RuleSpec, dimension_counts, dry_run

    pos = Position(tenant_id=tenant_id, name="Бариста")
    db.add(pos)
    await db.flush()
    await _mk_profile(db, tenant_id, email="b1@t.ru", position_id=pos.id)
    await _mk_profile(db, tenant_id, email="b2@t.ru", position_id=pos.id)
    await _mk_profile(db, tenant_id, email="other@t.ru")

    counts = await dimension_counts(db)
    seen, _sample = await dry_run(
        db,
        is_all=False,
        rules=[RuleSpec(mode="include", position_ids=frozenset({pos.id}))],
    )
    assert counts["position_ids"][str(pos.id)] == seen == 2


async def test_dimension_counts_follow_tu_assignments(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """ТУ считается в СВОИХ закреплённых магазинах.

    Наивный `GROUP BY store_id` дал бы ноль: у ТУ собственного магазина нет,
    точки приходят из `tu_store_assignments` через `build_attrs`.
    """
    from app.models.employee_profile import TuStoreAssignment
    from app.services.audience_resolver import dimension_counts

    store = Store(tenant_id=tenant_id, name="Невская, 3")
    db.add(store)
    await db.flush()
    tu = await _mk_profile(db, tenant_id, email="tu@t.ru")
    tu.org_role = "tu"
    db.add(TuStoreAssignment(tenant_id=tenant_id, profile_id=tu.id, store_id=store.id))
    await db.flush()

    counts = await dimension_counts(db)
    assert counts["store_ids"][str(store.id)] == 1


async def test_dimension_counts_gated_like_dry_run(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Числа складываются в состав штата — гейт publisher+, как у dry-run."""
    from fastapi import HTTPException

    from app.api.org import audience_dimension_counts
    from tests.integration.test_courses import _mk_member
    from tests.integration.test_quizzes import _mk_publisher

    line, _profile = await _mk_member(db, tenant_id, email="line@t.ru")
    with pytest.raises(HTTPException) as exc:
        await audience_dimension_counts(principal=line, db=db)
    assert exc.value.status_code == 403

    hr, _hr_profile = await _mk_publisher(db, tenant_id)
    out = await audience_dimension_counts(principal=hr, db=db)
    assert "position_ids" in out.counts and "org_roles" in out.counts

"""RLS-инвариант переживает mid-request commit + смену соединения в пуле.

Регрессия инцидента 2026-08-01 (прод): `tenant_scoped_session` ставил
`app.tenant_id` session-level один раз при открытии сессии, но `get_db`
коммитит shadow-upsert'ы ДО yield — соединение возвращалось в пул, и
бизнес-запросы роута исполнялись на другом соединении со stale-GUC чужого
tenant'а. Симптомы: кросс-tenant чтения (Пётр видел проекты UPPETIT),
флаппинг 404/200 одного URL, `/api/me` 500 (InsufficientPrivilegeError
на INSERT employee_profiles).

Фикс: листенер `app.db._apply_rls_on_begin` перепроставляет GUC через
`SET LOCAL` в начале каждой транзакции. Тесты эмулируют «грязное»
соединение явно (session-level set_config чужим tenant'ом после commit) —
детерминированно, без рулетки пула.

Все тесты — под `rls_enforced` (non-superuser роль): под superuser'ом
testcontainers RLS не enforced, и контрольный ассерт
`test_rls_blocks_other_tenant_after_commit` упал бы — тест не может
молча деградировать в no-op.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.db import bypass_session_factory, tenant_scoped_session

pytestmark = pytest.mark.integration


async def _seed_shadow_user(tenant_id: uuid.UUID, employee_id: uuid.UUID) -> None:
    """Seed shadow_tenants (no-RLS) + shadow_users (FORCE RLS) через bypass."""
    async with tenant_scoped_session(None, bypass_rls=True) as s:
        await s.execute(
            text(
                "INSERT INTO shadow_tenants (id, slug, name, status) "
                "VALUES (:tid, :slug, 'T', 'active') ON CONFLICT (id) DO NOTHING"
            ),
            {"tid": tenant_id, "slug": f"t-{tenant_id.hex[:12]}"},
        )
        await s.execute(
            text(
                "INSERT INTO shadow_users (employee_id, tenant_id, email, full_name) "
                "VALUES (:eid, :tid, :email, 'N')"
            ),
            {
                "eid": employee_id,
                "tid": tenant_id,
                "email": f"{employee_id.hex[:12]}@test.ru",
            },
        )
        await s.commit()


async def _pollute_connection(s, wrong_tenant: uuid.UUID) -> None:
    """Эмуляция stale-GUC: session-level set_config чужим tenant'ом + commit.

    До фикса следующий запрос унаследовал бы эти значения (bypass сброшен,
    то есть RLS реально enforced, не bypass'ит) и работал бы в чужом scope.
    """
    await s.execute(
        text("SELECT set_config('app.tenant_id', :w, false)"),
        {"w": str(wrong_tenant)},
    )
    await s.execute(text("SELECT set_config('app.bypass_rls', '', false)"))
    await s.commit()


@pytest.mark.asyncio
async def test_rls_survives_mid_session_commit(rls_enforced) -> None:
    """После mid-request commit + грязного GUC SELECT всё ещё видит свою строку."""
    tenant_id = uuid.uuid4()
    other_tenant = uuid.uuid4()
    employee_id = uuid.uuid4()
    await _seed_shadow_user(tenant_id, employee_id)

    async with tenant_scoped_session(tenant_id) as s:
        found = (
            await s.execute(
                text("SELECT employee_id FROM shadow_users WHERE employee_id = :e"),
                {"e": employee_id},
            )
        ).scalar_one_or_none()
        assert found == employee_id

        # Mid-request commit — паттерн get_db (shadow-upsert до yield).
        await s.commit()
        await _pollute_connection(s, other_tenant)

        # Листенер after_begin перезатёр LOCAL GUC → строка снова видна.
        found2 = (
            await s.execute(
                text("SELECT employee_id FROM shadow_users WHERE employee_id = :e"),
                {"e": employee_id},
            )
        ).scalar_one_or_none()
        assert found2 == employee_id


@pytest.mark.asyncio
async def test_rls_blocks_other_tenant_after_commit(rls_enforced) -> None:
    """Контроль: фикс не «открывает всё» — чужая строка невидима.

    Этот ассерт заодно доказывает, что RLS реально enforced (под superuser
    он падает — видны оба tenant'а).
    """
    tenant_id = uuid.uuid4()
    other_tenant = uuid.uuid4()
    mine = uuid.uuid4()
    theirs = uuid.uuid4()
    await _seed_shadow_user(tenant_id, mine)
    await _seed_shadow_user(other_tenant, theirs)

    async with tenant_scoped_session(tenant_id) as s:
        await s.commit()  # mid-request commit + возврат соединения в пул
        visible = set(
            (
                await s.execute(
                    text(
                        "SELECT employee_id FROM shadow_users "
                        "WHERE employee_id IN (:a, :b)"
                    ),
                    {"a": mine, "b": theirs},
                )
            )
            .scalars()
            .all()
        )
        assert mine in visible
        assert theirs not in visible


@pytest.mark.asyncio
async def test_insert_own_tenant_after_dirty_guc(rls_enforced) -> None:
    """Сценарий /api/me из инцидента: INSERT со своим tenant_id проходит.

    До фикса WITH CHECK сравнивал строку с чужим stale-GUC →
    InsufficientPrivilegeError («new row violates row-level security
    policy for employee_profiles») — та самая 500-ка.
    """
    tenant_id = uuid.uuid4()
    other_tenant = uuid.uuid4()
    employee_id = uuid.uuid4()
    await _seed_shadow_user(tenant_id, employee_id)

    async with tenant_scoped_session(tenant_id) as s:
        await s.commit()
        await _pollute_connection(s, other_tenant)

        profile_id = uuid.uuid4()
        await s.execute(
            text(
                "INSERT INTO employee_profiles "
                "(id, tenant_id, employee_id, email, full_name) "
                "VALUES (:id, :tid, :eid, :email, 'N')"
            ),
            {
                "id": profile_id,
                "tid": tenant_id,
                "eid": employee_id,
                "email": f"{employee_id.hex[:12]}@test.ru",
            },
        )
        await s.commit()
        created = (
            await s.execute(
                text("SELECT tenant_id FROM employee_profiles WHERE id = :id"),
                {"id": profile_id},
            )
        ).scalar_one()
        assert created == tenant_id


@pytest.mark.asyncio
async def test_bypass_session_factory_sees_all_tenants(rls_enforced) -> None:
    """Страховка deletion-sync: bypass-фабрика видит/правит shadow_users всех
    tenant'ов (эмуляция mark_shadow_deleted из signaris_auth.sync)."""
    t1, t2 = uuid.uuid4(), uuid.uuid4()
    e1, e2 = uuid.uuid4(), uuid.uuid4()
    await _seed_shadow_user(t1, e1)
    await _seed_shadow_user(t2, e2)

    factory = bypass_session_factory()
    async with factory() as s:
        visible = set(
            (
                await s.execute(
                    text(
                        "SELECT employee_id FROM shadow_users "
                        "WHERE employee_id IN (:a, :b)"
                    ),
                    {"a": e1, "b": e2},
                )
            )
            .scalars()
            .all()
        )
        assert visible == {e1, e2}

        # mark_shadow_deleted-паттерн: UPDATE чужого tenant'а проходит.
        result = await s.execute(
            text(
                "UPDATE shadow_users SET deleted_at = now() "
                "WHERE employee_id = :e"
            ),
            {"e": e2},
        )
        assert result.rowcount == 1
        await s.commit()

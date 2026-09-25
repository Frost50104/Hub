"""Учётки касс для «Оргструктура → Точки» (`GET /learn/org/points/accounts`).

С 16.09 ручка отвечала 500: `ee4d9ec` перенёс `auth_state_for` и
`staff_snapshot_fresh` из `app.api.employees` в `app.services.auth_state`, а
локальный импорт внутри ручки остался старым. ImportError срабатывал только при
вызове, и ни один тест ручку не вызывал — вкладка «Точки» показывала «учётки
нет» у каждой точки. Импорт теперь на уровне модуля, а этот тест ручку зовёт.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.org import point_accounts
from tests.integration._race_seed import seed_network

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _rls(rls_enforced):  # noqa: ARG001 — фикстура нужна побочным эффектом
    yield


async def test_point_accounts_lists_cash_accounts(db: AsyncSession, tenant_id):
    net = await seed_network(db, tenant_id, enable=False)

    rows = await point_accounts(principal=net.admin, db=db)

    assert [(r.full_name, r.store_id) for r in rows] == [("cashier_a", net.A.id)]

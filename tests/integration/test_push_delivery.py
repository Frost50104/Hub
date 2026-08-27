"""Подписки: продление свежести, гейт и самопроверка.

Инцидент 26.08 показал две вещи. Первая — транспорт был сломан месяц
(покрыто `tests/unit/test_push_vapid.py`). Вторая — узнать об этом было
неоткуда: `last_seen_at` двигался ТОЛЬКО при успешной отправке, а способа
проверить доставку изнутри продукта не существовало.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.push import send_test_push, subscribe
from app.config import get_settings
from app.models.push_subscription import PushSubscription
from app.schemas.notification import PushSubscribeBody
from app.services import push_sender
from tests.integration.conftest import make_principal
from tests.integration.test_project_access import _register

pytestmark = pytest.mark.integration

ENDPOINT = "https://web.push.apple.com/QHT-JWQuGN5_7BqJVO-example"


def _body(endpoint: str = ENDPOINT) -> PushSubscribeBody:
    return PushSubscribeBody.model_validate(
        {
            "endpoint": endpoint,
            "keys": {"p256dh": "p" * 60, "auth": "a" * 22},
            "user_agent": "QA-Browser/1.0",
        }
    )


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    from app.api import push as push_api

    async def _noop(**kw) -> None:
        return None

    monkeypatch.setattr(push_api, "enforce_rate_limit", _noop)


async def _last_seen(db: AsyncSession, endpoint: str) -> datetime:
    return (
        await db.execute(
            select(PushSubscription.last_seen_at).where(
                PushSubscription.endpoint == endpoint
            )
        )
    ).scalar_one()


async def test_resubscribe_extends_freshness(db: AsyncSession, tenant_id: uuid.UUID):
    """Повторная подписка ПРОДЛЕВАЕТ срок — на этом держится гейт свежести.

    Тихая переподписка при запуске PWA шлёт ту же ручку; не продлевай она
    `last_seen_at`, гейт превратился бы в выключатель пушей.
    """
    person = make_principal(tenant_id, email="push1@t.ru", tenant_slug="push1")
    await _register(db, person)
    await db.commit()

    await subscribe(_body(), person, db)
    # Отматываем назад, как будто подписка стоит давно.
    await db.execute(
        update(PushSubscription)
        .where(PushSubscription.endpoint == ENDPOINT)
        .values(last_seen_at=datetime.now(UTC) - timedelta(days=100))
    )
    await db.commit()
    stale = await _last_seen(db, ENDPOINT)

    await subscribe(_body(), person, db)
    assert await _last_seen(db, ENDPOINT) > stale


async def test_stale_subscription_is_skipped_but_counted(
    db: AsyncSession, tenant_id: uuid.UUID, monkeypatch
):
    """Протухшую подписку не трогаем, но человеку о ней говорим.

    «Подписок нет» и «подписка давно не подтверждалась» — разные беды с разным
    лечением, и ответ обязан их различать.
    """
    person = make_principal(tenant_id, email="push2@t.ru", tenant_slug="push2")
    await _register(db, person)
    await db.commit()
    await subscribe(_body(), person, db)
    await db.execute(
        update(PushSubscription)
        .where(PushSubscription.endpoint == ENDPOINT)
        .values(
            last_seen_at=datetime.now(UTC)
            - timedelta(days=get_settings().push_freshness_days + 1)
        )
    )
    await db.commit()

    sent: list[str] = []
    monkeypatch.setattr(push_sender, "load_vapid", lambda: object())
    monkeypatch.setattr(
        push_sender, "_send_blocking", lambda **kw: sent.append(kw["endpoint"]) or 201
    )

    result = await send_test_push(person, db)
    assert sent == [], "по протухшей подписке слать нельзя"
    assert result.subscriptions == 1
    assert result.stale == 1
    assert result.ok is False
    assert "подтверждал" in result.detail.lower()


async def test_fresh_subscription_receives_the_test_push(
    db: AsyncSession, tenant_id: uuid.UUID, monkeypatch
):
    person = make_principal(tenant_id, email="push3@t.ru", tenant_slug="push3")
    await _register(db, person)
    await db.commit()
    await subscribe(_body(), person, db)

    monkeypatch.setattr(push_sender, "load_vapid", lambda: object())
    monkeypatch.setattr(push_sender, "_send_blocking", lambda **kw: 201)

    result = await send_test_push(person, db)
    assert result.ok is True
    assert result.sent == 1
    assert result.stale == 0


async def test_dead_subscription_is_removed_and_explained(
    db: AsyncSession, tenant_id: uuid.UUID, monkeypatch
):
    """410 от транспорта = браузер выбросил подписку: чистим и говорим об этом."""
    from pywebpush import WebPushException

    person = make_principal(tenant_id, email="push4@t.ru", tenant_slug="push4")
    await _register(db, person)
    await db.commit()
    await subscribe(_body(), person, db)

    class _Resp:
        status_code = 410

    def _gone(**kw):
        raise WebPushException("gone", response=_Resp())

    monkeypatch.setattr(push_sender, "load_vapid", lambda: object())
    monkeypatch.setattr(push_sender, "_send_blocking", _gone)

    result = await send_test_push(person, db)
    assert result.removed == 1
    assert result.ok is False
    assert "заново" in result.detail
    assert (
        await db.execute(
            select(PushSubscription).where(PushSubscription.endpoint == ENDPOINT)
        )
    ).first() is None


async def test_no_subscriptions_answers_plainly(
    db: AsyncSession, tenant_id: uuid.UUID, monkeypatch
):
    person = make_principal(tenant_id, email="push5@t.ru", tenant_slug="push5")
    await _register(db, person)
    await db.commit()
    monkeypatch.setattr(push_sender, "load_vapid", lambda: object())

    result = await send_test_push(person, db)
    assert result.subscriptions == 0
    assert result.ok is False
    assert "не подписано" in result.detail


async def test_push_disabled_on_server_says_so(
    db: AsyncSession, tenant_id: uuid.UUID, monkeypatch
):
    """Без ключа человек должен услышать про сервер, а не про своё устройство."""
    person = make_principal(tenant_id, email="push6@t.ru", tenant_slug="push6")
    await _register(db, person)
    await db.commit()
    await subscribe(_body(), person, db)
    monkeypatch.setattr(push_sender, "load_vapid", lambda: None)

    result = await send_test_push(person, db)
    assert result.ok is False
    assert "администратор" in result.detail

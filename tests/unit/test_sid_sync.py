"""Часовой над догоном sid-sync при старте.

Тест узкий и на первый взгляд формальный — проверяет, что `start_worker`
передаёт воркеру `bootstrap_window_sec`. Смысл в том, что удаление этой опции
вернёт баг МОЛЧА: в логах не появится ни ошибки, ни строки `sid_sync.bootstrap`,
только `store_size` начнёт расходиться с фидом, а на него никто не смотрит.
Сам догон и защиту от откатa фида проверяет либа (`signaris_auth.sid_sync`),
дублировать её тесты здесь нечего.

Замер 18.09, из-за которого опция и появилась: в фиде было 137 событий, а
`store_size` прод-процесса — 39, то есть процесс не знал примерно про 98
отозванных сессий, попавших в фид до его старта.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from app.config import get_settings


@pytest.fixture
def _service_key(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Непустой service-key: без него `start_worker` выходит до вызова воркера.

    Кэш `get_settings` чистится с ОБЕИХ сторон. Иначе подменённые настройки
    утекут в соседние тесты — ровно так протекает образец в `test_config.py`,
    где `cache_clear()` есть только до подмены.
    """
    monkeypatch.setenv("SIGNARIS_HUB_SIGNARIS_SERVICE_KEY", "svc_test_key")
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_start_worker_enables_bootstrap(
    monkeypatch: pytest.MonkeyPatch, _service_key: None
) -> None:
    from app.services import sid_sync

    captured: dict[str, Any] = {}

    async def fake_worker(**kwargs: Any) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(sid_sync, "run_sid_sync_worker", fake_worker)
    await sid_sync.start_worker()

    # Сутки: TTL access-токена 15 минут перекрыт с большим запасом.
    assert captured["bootstrap_window_sec"] == 86_400.0
    assert sid_sync.BOOTSTRAP_WINDOW_SEC >= 15 * 60, "окно обязано перекрывать TTL access"


@pytest.mark.asyncio
async def test_start_worker_keeps_cursor_callbacks(
    monkeypatch: pytest.MonkeyPatch, _service_key: None
) -> None:
    """Курсор остаётся персистентным — догон его не заменяет, а дополняет."""
    from app.services import sid_sync

    captured: dict[str, Any] = {}

    async def fake_worker(**kwargs: Any) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(sid_sync, "run_sid_sync_worker", fake_worker)
    await sid_sync.start_worker()

    assert captured["load_cursor"] is sid_sync._load_cursor
    assert captured["save_cursor"] is sid_sync._save_cursor


@pytest.mark.asyncio
async def test_start_worker_without_service_key_does_not_call_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Нет ключа — воркер не зовём вовсе (иначе фид отвечал бы 401 по кругу)."""
    from app.services import sid_sync

    monkeypatch.setenv("SIGNARIS_HUB_SIGNARIS_SERVICE_KEY", "")
    get_settings.cache_clear()
    called = False

    async def fake_worker(**_: Any) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(sid_sync, "run_sid_sync_worker", fake_worker)
    try:
        await sid_sync.start_worker()
    finally:
        get_settings.cache_clear()

    assert called is False

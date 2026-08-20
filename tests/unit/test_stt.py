"""Голосовой ввод (волна 3): границы ручки и изоляция модели.

Главное здесь — не качество распознавания (оно замеряется на живом железе),
а то, что API-процесс НЕ тянет в себя веса модели и внятно отвечает, когда
голос не настроен или сервис недоступен.
"""

from __future__ import annotations

import sys

import pytest
from fastapi import HTTPException

from app.config import get_settings


@pytest.fixture(autouse=True)
def _clear_settings():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_api_process_never_imports_the_model():
    """`faster_whisper` весит сотни мегабайт в RSS. Если он окажется в
    API-процессе, отдельный юнит с MemoryMax теряет смысл."""
    import app.api.assistant  # noqa: F401
    import app.main  # noqa: F401

    assert "faster_whisper" not in sys.modules
    assert "ctranslate2" not in sys.modules


def test_stt_service_module_is_importable_without_the_model():
    """Юнит должен подниматься и отвечать /health, даже пока модель не
    загружена: загрузка ленивая, по первому запросу."""
    import app.stt_service as svc

    assert svc.app is not None
    assert "faster_whisper" not in sys.modules


async def test_transcribe_is_503_when_voice_is_off(monkeypatch):
    from app.api.assistant import transcribe

    monkeypatch.setenv("SIGNARIS_HUB_STT_ENABLED", "false")
    get_settings.cache_clear()

    with pytest.raises(HTTPException) as exc:
        await transcribe(request=None, principal=None)  # до тела не дойдёт
    assert exc.value.status_code == 503


async def test_transcribe_rejects_oversized_audio(monkeypatch):
    """2 МБ ≈ десять минут opus. Команда голосом — это секунды, и принимать
    длинные записи значит занимать оба ядра VPS на минуты."""
    from types import SimpleNamespace

    from app.api.assistant import transcribe

    monkeypatch.setenv("SIGNARIS_HUB_STT_ENABLED", "true")
    monkeypatch.setenv("SIGNARIS_HUB_STT_MAX_BYTES", "1024")
    get_settings.cache_clear()

    async def body() -> bytes:
        return b"x" * 2048

    request = SimpleNamespace(body=body, headers={"content-type": "audio/webm"})
    principal = SimpleNamespace(employee_id="00000000-0000-0000-0000-000000000001")

    async def no_rate_limit(**kwargs):
        return None

    monkeypatch.setattr("app.api.assistant.enforce_rate_limit", no_rate_limit)
    with pytest.raises(HTTPException) as exc:
        await transcribe(request=request, principal=principal)
    assert exc.value.status_code == 413


async def test_transcribe_says_so_when_service_is_down(monkeypatch):
    """Юнит упал или ещё грузит модель — сотрудник должен узнать, что можно
    набрать текстом, а не получить безликую 502."""
    from types import SimpleNamespace

    import httpx

    from app.api.assistant import transcribe

    monkeypatch.setenv("SIGNARIS_HUB_STT_ENABLED", "true")
    monkeypatch.setenv("SIGNARIS_HUB_STT_PROVIDER", "local")
    monkeypatch.setenv("SIGNARIS_HUB_STT_URL", "http://127.0.0.1:9")
    get_settings.cache_clear()

    async def body() -> bytes:
        return b"x" * 4096

    request = SimpleNamespace(body=body, headers={"content-type": "audio/webm"})
    principal = SimpleNamespace(employee_id="00000000-0000-0000-0000-000000000001")

    async def no_rate_limit(**kwargs):
        return None

    monkeypatch.setattr("app.api.assistant.enforce_rate_limit", no_rate_limit)

    class DeadClient:
        def __init__(self, *a, **kw): ...
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return None
        async def post(self, *a, **kw):
            raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "AsyncClient", DeadClient)
    with pytest.raises(HTTPException) as exc:
        await transcribe(request=request, principal=principal)
    assert exc.value.status_code == 503
    assert "текстом" in exc.value.detail

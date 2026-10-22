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


# ─── Сервис распознавания: предзагрузка, отказы, занятость (21–22.10) ───────
#
# До 22.10 модель грузилась ленивой первой командой и выгружалась по простою,
# а отметка простоя ставилась только после УСПЕШНОЙ расшифровки — 09.09 модель
# «выгрузили» посреди работы, и юнит шесть недель висел незамеченным
# (docs/tech-debt/incidents.md). Ниже — правила, которые это закрывают.


@pytest.fixture
def stt_local(monkeypatch):
    """Чистое состояние модуля: глобальные переменные и замок на каждый тест."""
    import asyncio

    from app.services.stt import local

    monkeypatch.setattr(local, "_model", None)
    monkeypatch.setattr(local, "_state", "loading")
    monkeypatch.setattr(local, "_busy_since", None)
    monkeypatch.setattr(local, "_lock", asyncio.Lock())
    return local


def _ready(local, monkeypatch):
    monkeypatch.setattr(local, "_model", object())
    monkeypatch.setattr(local, "_state", "ready")


async def test_preload_marks_ready_and_is_busy_while_loading(stt_local, monkeypatch):
    """Загрузка — тоже работа под замком: зависшую загрузку видит сторож."""
    monkeypatch.setenv("SIGNARIS_HUB_STT_CACHE_DIR", "/srv/stt-cache/hub")
    get_settings.cache_clear()
    seen = {}

    def fake_load(name, compute_type, threads, cache_dir):
        seen["busy"] = stt_local.busy_seconds()
        seen["cache_dir"] = cache_dir
        return object()

    monkeypatch.setattr(stt_local, "_load", fake_load)
    await stt_local.preload()

    assert stt_local.state() == "ready"
    assert seen["busy"] is not None
    # Каталог кэша один для юнита и для app.jobs.stt_fetch_model.
    assert seen["cache_dir"] == "/srv/stt-cache/hub"
    assert stt_local.busy_seconds() is None


@pytest.mark.parametrize(
    ("exc", "state"),
    [(FileNotFoundError("snapshot not cached"), "missing"), (RuntimeError("ctranslate2"), "error")],
)
async def test_preload_failure_is_a_state_not_a_crash(stt_local, monkeypatch, exc, state):
    """Под HF_HUB_OFFLINE=1 модели может не быть в кэше: сервис остаётся жив,
    `/health` говорит `missing`/`error`, а запрос получает 503 с текстом."""
    from app.services.stt import STTUnavailable

    def fake_load(*_args):
        raise exc

    monkeypatch.setattr(stt_local, "_load", fake_load)
    await stt_local.preload()

    assert stt_local.state() == state
    assert stt_local.busy_seconds() is None
    with pytest.raises(STTUnavailable) as err:
        await stt_local.LocalWhisper().transcribe(b"x", content_type="audio/webm")
    assert "текстом" in str(err.value)


def test_missing_snapshot_error_of_huggingface_hub_is_file_not_found():
    """`preload` ловит FileNotFoundError, а не класс huggingface_hub: так модуль
    не тянет библиотеку в импорт. Держится, пока LocalEntryNotFoundError —
    её подкласс (проверено на 1.28 и 1.29)."""
    errors = pytest.importorskip("huggingface_hub.errors")
    assert issubclass(errors.LocalEntryNotFoundError, FileNotFoundError)


async def test_too_long_recording_is_rejected_before_transcription(stt_local, monkeypatch):
    """Минута звука — ~25 с работы на двух ядрах; длиннее — 413 сразу после
    декодирования, модель не трогается."""
    from app.services.stt import STTTooLong

    monkeypatch.setenv("SIGNARIS_HUB_STT_MAX_AUDIO_SEC", "60")
    get_settings.cache_clear()
    _ready(stt_local, monkeypatch)
    monkeypatch.setattr(stt_local, "_decode", lambda _audio: [0.0] * (61 * stt_local.SAMPLE_RATE))
    ran = []
    monkeypatch.setattr(stt_local, "_run", lambda *_a: ran.append(1) or "текст")

    with pytest.raises(STTTooLong) as err:
        await stt_local.LocalWhisper().transcribe(b"x", content_type="audio/webm")
    assert "60 с" in str(err.value)
    assert ran == []
    assert stt_local.busy_seconds() is None


async def test_abandoned_request_is_not_decoded(stt_local, monkeypatch):
    """uvicorn не отменяет обработчик, когда клиент ушёл: запрос, брошенный
    основным приложением по таймауту, не должен занимать ядра."""
    from app.services.stt import STTUnavailable

    _ready(stt_local, monkeypatch)
    decoded = []
    monkeypatch.setattr(stt_local, "_decode", lambda _audio: decoded.append(1) or [0.0])

    async def gone() -> bool:
        return True

    with pytest.raises(STTUnavailable):
        await stt_local.LocalWhisper().transcribe(
            b"x", content_type="audio/webm", is_abandoned=gone
        )
    assert decoded == []


async def test_transcription_is_busy_while_running_and_free_after(stt_local, monkeypatch):
    _ready(stt_local, monkeypatch)
    monkeypatch.setattr(stt_local, "_decode", lambda _audio: [0.0] * stt_local.SAMPLE_RATE)
    seen = {}

    def fake_run(_model, _samples, _language):
        seen["busy"] = stt_local.busy_seconds()
        return "поставь задачу на пятницу"

    monkeypatch.setattr(stt_local, "_run", fake_run)
    result = await stt_local.LocalWhisper().transcribe(b"x", content_type="audio/webm")

    assert result.text == "поставь задачу на пятницу"
    assert result.duration_sec == 1.0
    assert seen["busy"] is not None
    assert stt_local.busy_seconds() is None


async def test_failed_transcription_frees_busy(stt_local, monkeypatch):
    """Упавшая расшифровка не оставляет «занято»: иначе сторож через
    stt_max_busy_sec перезапустил бы здоровый юнит."""
    from app.services.stt import STTError

    _ready(stt_local, monkeypatch)
    monkeypatch.setattr(stt_local, "_decode", lambda _audio: [0.0] * stt_local.SAMPLE_RATE)

    def broken(*_a):
        raise ValueError("decoder")

    monkeypatch.setattr(stt_local, "_run", broken)
    with pytest.raises(STTError):
        await stt_local.LocalWhisper().transcribe(b"x", content_type="audio/webm")
    assert stt_local.busy_seconds() is None


async def test_health_reports_model_state(stt_local, monkeypatch):
    """healthcheck и app.jobs.stt_smoke читают `status`; 200 — только `ready`."""
    import json

    import app.stt_service as svc

    monkeypatch.setenv("SIGNARIS_HUB_STT_ENABLED", "true")
    monkeypatch.setenv("SIGNARIS_HUB_STT_PROVIDER", "local")
    get_settings.cache_clear()
    for state, code in (("ready", 200), ("loading", 503), ("missing", 503), ("error", 503)):
        monkeypatch.setattr(stt_local, "_state", state)
        resp = await svc.health()
        assert resp.status_code == code
        assert json.loads(resp.body)["status"] == state


async def test_health_without_local_stt_is_disabled(monkeypatch):
    import json

    import app.stt_service as svc

    monkeypatch.setenv("SIGNARIS_HUB_STT_ENABLED", "false")
    get_settings.cache_clear()
    resp = await svc.health()
    assert resp.status_code == 200
    assert json.loads(resp.body)["status"] == "disabled"


@pytest.mark.parametrize(
    ("exc_name", "code"),
    [("STTTooLong", 413), ("STTUnavailable", 503), ("STTError", 502)],
)
async def test_service_maps_errors_to_status(monkeypatch, exc_name, code):
    from types import SimpleNamespace

    import app.services.stt as stt_pkg
    import app.stt_service as svc
    from app.services.stt.local import LocalWhisper

    exc = getattr(stt_pkg, exc_name)("причина для человека")

    class Failing(LocalWhisper):
        async def transcribe(self, audio, *, content_type, is_abandoned=None):
            raise exc

    monkeypatch.setattr(svc, "get_stt", lambda: Failing())

    async def body() -> bytes:
        return b"x" * 64

    async def connected() -> bool:
        return False

    request = SimpleNamespace(
        body=body, headers={"content-type": "audio/webm"}, is_disconnected=connected
    )
    with pytest.raises(HTTPException) as err:
        await svc.transcribe(request)
    assert err.value.status_code == code
    assert err.value.detail == "причина для человека"


# ─── Основное приложение: что доходит до человека ───────────────────────────


def _proxy_request(monkeypatch, response=None, raise_exc=None):
    from types import SimpleNamespace

    import httpx

    monkeypatch.setenv("SIGNARIS_HUB_STT_ENABLED", "true")
    monkeypatch.setenv("SIGNARIS_HUB_STT_PROVIDER", "local")
    get_settings.cache_clear()

    async def body() -> bytes:
        return b"x" * 4096

    async def no_rate_limit(**kwargs):
        return None

    monkeypatch.setattr("app.api.assistant.enforce_rate_limit", no_rate_limit)

    class Client:
        def __init__(self, *a, **kw): ...

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def post(self, *a, **kw):
            if raise_exc is not None:
                raise raise_exc
            return response

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    request = SimpleNamespace(body=body, headers={"content-type": "audio/webm"})
    principal = SimpleNamespace(employee_id="00000000-0000-0000-0000-000000000001")
    return request, principal


@pytest.mark.parametrize(
    ("status", "detail"),
    [
        (413, "Запись длиннее 60 с — скажите короче"),
        (503, "Распознавание речи запускается — попробуйте через минуту или наберите текстом"),
    ],
)
async def test_transcribe_passes_stt_reason_through(monkeypatch, status, detail):
    """Причину для человека формулирует сервис распознавания; до 22.10 её
    заменяла общая фраза, и 413 про длину уходил безликим."""
    import httpx

    from app.api.assistant import transcribe

    request, principal = _proxy_request(
        monkeypatch, response=httpx.Response(status, json={"detail": detail})
    )
    with pytest.raises(HTTPException) as err:
        await transcribe(request=request, principal=principal)
    assert err.value.status_code == status
    assert err.value.detail == detail


async def test_transcribe_hides_internal_failure_text(monkeypatch):
    """502 сервиса несёт текст исключения декодера — наружу общая фраза."""
    import httpx

    from app.api.assistant import transcribe

    request, principal = _proxy_request(
        monkeypatch, response=httpx.Response(502, json={"detail": "av.error.InvalidDataError"})
    )
    with pytest.raises(HTTPException) as err:
        await transcribe(request=request, principal=principal)
    assert err.value.status_code == 502
    assert "av.error" not in err.value.detail
    assert "текстом" in err.value.detail


async def test_unreachable_log_names_the_error_kind(monkeypatch):
    """У таймаута httpx пустой текст: 09.09 в журнале осталось `error=""`."""
    import httpx
    from structlog.testing import capture_logs

    from app.api.assistant import transcribe

    request, principal = _proxy_request(monkeypatch, raise_exc=httpx.ReadTimeout(""))
    with capture_logs() as logs, pytest.raises(HTTPException) as err:
        await transcribe(request=request, principal=principal)
    assert err.value.status_code == 503
    entry = next(e for e in logs if e["event"] == "stt.unreachable")
    assert entry["kind"] == "ReadTimeout"


async def test_status_reports_voice_limit_only_for_local_stt(monkeypatch):
    """Микрофон останавливает запись сам у предела — предел приезжает из
    `/ai/status`, второй константы на клиенте нет."""
    from app.api.assistant import status

    monkeypatch.setenv("SIGNARIS_HUB_STT_ENABLED", "true")
    monkeypatch.setenv("SIGNARIS_HUB_STT_PROVIDER", "local")
    monkeypatch.setenv("SIGNARIS_HUB_STT_MAX_AUDIO_SEC", "60")
    get_settings.cache_clear()
    resp = await status(_principal=None)
    assert resp.voice is True
    assert resp.voice_max_sec == 60

    monkeypatch.setenv("SIGNARIS_HUB_STT_PROVIDER", "openai")
    get_settings.cache_clear()
    assert (await status(_principal=None)).voice_max_sec is None

    monkeypatch.setenv("SIGNARIS_HUB_STT_ENABLED", "false")
    get_settings.cache_clear()
    assert (await status(_principal=None)).voice_max_sec is None

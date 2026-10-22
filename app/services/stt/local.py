"""faster-whisper внутри отдельного systemd-юнита.

Модуль НЕ импортируется основным приложением: `ctranslate2` и веса модели не
должны попадать в адресное пространство API-процесса.

Замер на VPS 22.10 (2 vCPU, 4 ГБ, swap нет; `scripts/stt_measure.py`, версии —
пины `[stt]` в pyproject): загрузка `small` — 3,4 с и пик 540 МБ anon,
расшифровка — пик 741 МБ anon, четырёхсекундная команда — 5,6 с, длинная
запись — 0,41 с работы на секунду звука. Отсюда правила:

- **модель загружается при старте юнита и не выгружается** (решение владельца
  22.10). На 4 ГБ это ~640 МБ постоянно, зато пик памяти и «модель не
  скачана» видны сразу после деплоя, а не на первой команде сотрудника.
  Выгрузка по простою в августе возвращала лишь 757 → 425 МБ, а её отметка
  `_last_used` ставилась только после успешной расшифровки — и 09.09 модель
  «выгрузили» посреди работы;
- **модель берётся только из кэша** (`HF_HUB_OFFLINE=1` в юните, скачивает
  `app.jobs.stt_fetch_model`). Скачивание внутри процесса 09.09 оставило
  ~230 МБ anon сверху (замер 22.10: 728 МБ после загрузки против 499), первая
  расшифровка дошла до 914 МБ — и юнит шесть недель простоял за
  `memory.high` (docs/tech-debt/incidents.md);
- **одна расшифровка за раз и не длиннее `stt_max_audio_sec`**: две
  параллельно займут оба ядра и задушат API, а минута звука — это ~25 с
  работы при таймауте основного приложения 90 с.

Сколько длится текущая работа, видит сторож (`watchdog.py`): дольше
`stt_max_busy_sec` — пинги systemd прекращаются, и юнит перезапускается.
"""

from __future__ import annotations

import asyncio
import io
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Literal

import structlog

from app.config import get_settings
from app.services.stt.base import STTError, STTTooLong, STTUnavailable, Transcript

log = structlog.get_logger("stt.local")

ModelState = Literal["loading", "ready", "missing", "error"]

SAMPLE_RATE = 16000

_model: Any | None = None
_state: ModelState = "loading"
# Начало текущей работы под замком — загрузки или расшифровки. None = свободен.
_busy_since: float | None = None
_lock = asyncio.Lock()

_NOT_READY: dict[str, str] = {
    "loading": "Распознавание речи запускается — попробуйте через минуту или наберите текстом",
    "missing": "Распознавание речи не настроено на сервере — наберите команду текстом",
    "error": "Распознавание речи сейчас недоступно — наберите команду текстом",
}


def state() -> ModelState:
    return _state


def busy_seconds(now: float | None = None) -> float | None:
    """Сколько длится текущая работа под замком; None — сервис свободен."""
    if _busy_since is None:
        return None
    return (time.monotonic() if now is None else now) - _busy_since


def memory_mb() -> dict[str, int]:
    """Текущая память процесса и его cgroup — в строки журнала, без пиков:
    VmHWM и `memory.peak` копятся за всю жизнь процесса и о запросе не скажут."""
    out: dict[str, int] = {}
    try:
        for row in Path("/proc/self/status").read_text().splitlines():
            if row.startswith("VmRSS:"):
                out["rss_mb"] = round(int(row.split()[1]) / 1024)
                break
        rel = Path("/proc/self/cgroup").read_text().splitlines()[0].split("::", 1)[-1]
        current = Path("/sys/fs/cgroup") / rel.lstrip("/") / "memory.current"
        out["cgroup_mb"] = round(int(current.read_text().split()[0]) / 1024 / 1024)
    except (OSError, ValueError, IndexError):
        pass
    return out


def _load(name: str, compute_type: str, threads: int, cache_dir: str | None) -> Any:
    from faster_whisper import WhisperModel

    started = time.monotonic()
    model = WhisperModel(
        name,
        device="cpu",
        compute_type=compute_type,
        cpu_threads=threads,
        download_root=cache_dir,
    )
    log.info(
        "stt.model_loaded",
        model=name,
        seconds=round(time.monotonic() - started, 1),
        **memory_mb(),
    )
    return model


def _decode(audio: bytes) -> Any:
    # Байты, а не временный файл: PyAV внутри faster-whisper читает webm/opus
    # (Chrome) и mp4/aac (Safari) — проверено на обоих контейнерах.
    from faster_whisper import decode_audio

    return decode_audio(io.BytesIO(audio), sampling_rate=SAMPLE_RATE)


def _run(model: Any, samples: Any, language: str) -> str:
    segments, _info = model.transcribe(
        samples,
        language=language,
        # beam_size=1: на двух ядрах жадный поиск втрое быстрее, а на коротких
        # командах разницы в тексте на замерах не было.
        beam_size=1,
        vad_filter=True,
    )
    return " ".join(s.text.strip() for s in segments).strip()


async def preload() -> None:
    """Загрузка модели при старте юнита; состояние читают `/health` и
    healthcheck. Запросы, пришедшие во время загрузки, ждут её на замке."""
    global _model, _state, _busy_since
    settings = get_settings()
    async with _lock:
        _state = "loading"
        _busy_since = time.monotonic()
        try:
            _model = await asyncio.to_thread(
                _load,
                settings.stt_model,
                settings.stt_compute_type,
                settings.stt_cpu_threads,
                settings.stt_cache_dir,
            )
            _state = "ready"
        except FileNotFoundError:
            # Сюда же LocalEntryNotFoundError huggingface_hub: под
            # HF_HUB_OFFLINE=1 модели нет в кэше. Скачать — app.jobs.stt_fetch_model.
            _state = "missing"
            log.warning("stt.model_missing", model=settings.stt_model)
        except Exception as e:  # noqa: BLE001 — ctranslate2 бросает RuntimeError и не только
            _state = "error"
            log.error(
                "stt.model_failed", model=settings.stt_model, error=f"{type(e).__name__}: {e}"
            )
        finally:
            _busy_since = None


class LocalWhisper:
    name = "local"

    async def transcribe(
        self,
        audio: bytes,
        *,
        content_type: str,
        is_abandoned: Callable[[], Awaitable[bool]] | None = None,
    ) -> Transcript:
        global _busy_since
        settings = get_settings()
        if _state in ("missing", "error"):
            raise STTUnavailable(_NOT_READY[_state])
        async with _lock:
            if _model is None:
                # Загрузка, которую ждали на замке, не удалась.
                raise STTUnavailable(_NOT_READY.get(_state, _NOT_READY["error"]))
            # uvicorn не отменяет обработчик, когда клиент ушёл: запрос, который
            # основное приложение бросило по таймауту, иначе занял бы оба ядра
            # ради ответа, которого никто не ждёт.
            if is_abandoned is not None and await is_abandoned():
                log.info("stt.abandoned")
                raise STTUnavailable("Запрос отменён")
            started = time.monotonic()
            _busy_since = started
            try:
                try:
                    samples = await asyncio.to_thread(_decode, audio)
                except Exception as e:  # noqa: BLE001 — декодер бросает что угодно
                    raise STTError(f"Не удалось прочитать запись: {e}") from None
                audio_sec = len(samples) / SAMPLE_RATE
                if audio_sec > settings.stt_max_audio_sec:
                    limit = round(settings.stt_max_audio_sec)
                    raise STTTooLong(f"Запись длиннее {limit} с — скажите короче")
                try:
                    text = await asyncio.to_thread(_run, _model, samples, settings.stt_language)
                except Exception as e:  # noqa: BLE001
                    raise STTError(f"Не удалось распознать запись: {e}") from None
            finally:
                _busy_since = None
        # Текста в журнале нет: там рабочие команды сотрудников.
        log.info(
            "stt.transcribed",
            audio_sec=round(audio_sec, 1),
            seconds=round(time.monotonic() - started, 1),
            **memory_mb(),
        )
        return Transcript(text=text, duration_sec=audio_sec)

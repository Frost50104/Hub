"""faster-whisper внутри отдельного systemd-юнита.

Модуль НЕ импортируется основным приложением: `ctranslate2` и веса модели не
должны попадать в адресное пространство API-процесса.

Три вещи продиктованы железом (VPS: 2 vCPU, 1.9 ГБ RAM, swap нет). Замерено
на этой машине 2026-08-20:

- модель `small` — пик 759 МБ и ~5.5 с на четырёхсекундную команду; `base`
  вдвое легче и втрое быстрее, но распознаёт «поставь на пятницу» как
  «на 5 ниццу», то есть ставит неверный срок. Качество здесь важнее секунд,
  поэтому по умолчанию `small`, а юнит ограничен `MemoryMax`;
- **одна расшифровка за раз**: две параллельно не влезут в память и займут
  оба ядра, задушив API. Очередь ждёт, а не запускает вторую;
- **выгрузка по простою**: держать 759 МБ занятыми круглые сутки на этой
  машине нельзя, а первый запрос после простоя стоит ~9 с загрузки.
"""

from __future__ import annotations

import asyncio
import io
import time
from typing import Any

import structlog

from app.config import get_settings
from app.services.stt.base import STTError, Transcript

log = structlog.get_logger("stt.local")

_model: Any | None = None
_model_name: str | None = None
_last_used = 0.0
_lock = asyncio.Lock()


def _load(name: str, compute_type: str, threads: int) -> Any:
    from faster_whisper import WhisperModel

    started = time.monotonic()
    model = WhisperModel(
        name, device="cpu", compute_type=compute_type, cpu_threads=threads
    )
    log.info("stt.model_loaded", model=name, seconds=round(time.monotonic() - started, 1))
    return model


def unload_if_idle(idle_sec: float) -> bool:
    """Отдать память, если моделью давно не пользовались."""
    global _model, _model_name
    if _model is None or time.monotonic() - _last_used < idle_sec:
        return False
    _model = None
    _model_name = None
    log.info("stt.model_unloaded", idle_sec=idle_sec)
    return True


class LocalWhisper:
    name = "local"

    async def transcribe(self, audio: bytes, *, content_type: str) -> Transcript:
        global _model, _model_name, _last_used
        settings = get_settings()
        async with _lock:
            if _model is None or _model_name != settings.stt_model:
                _model = await asyncio.to_thread(
                    _load,
                    settings.stt_model,
                    settings.stt_compute_type,
                    settings.stt_cpu_threads,
                )
                _model_name = settings.stt_model
            model = _model
            try:
                # Байты, а не временный файл: faster-whisper декодирует
                # webm/opus (Chrome) и mp4/aac (Safari) через PyAV — проверено
                # на обоих контейнерах.
                text, duration = await asyncio.to_thread(
                    _run, model, audio, settings.stt_language
                )
            except Exception as e:  # noqa: BLE001 — декодер бросает что угодно
                raise STTError(f"Не удалось распознать запись: {e}") from None
            _last_used = time.monotonic()
        return Transcript(text=text, duration_sec=duration)


def _run(model: Any, audio: bytes, language: str) -> tuple[str, float]:
    segments, info = model.transcribe(
        io.BytesIO(audio),
        language=language,
        # beam_size=1: на двух ядрах жадный поиск втрое быстрее, а на коротких
        # командах разницы в тексте на замерах не было.
        beam_size=1,
        vad_filter=True,
    )
    text = " ".join(s.text.strip() for s in segments).strip()
    return text, float(getattr(info, "duration", 0.0) or 0.0)

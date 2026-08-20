"""Распознавание речи: контракт и ошибки.

Провайдер выбирается конфигом, как у LLM:
- `local` — faster-whisper в ОТДЕЛЬНОМ systemd-юните (см. `app/stt_service.py`).
  Бесплатно и без внешних сервисов, но модель ест сотни мегабайт, поэтому
  живёт вне основного процесса;
- `openai` — совместимый `/audio/transcriptions` (платно, одна переменная).

Без настройки ручка отвечает 503, и фронт просто не рисует микрофон.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class STTError(RuntimeError):
    """Сбой распознавания — API мапит в 502."""


class STTNotConfigured(RuntimeError):
    """Голосовой ввод выключен или не настроен — API мапит в 503."""


@dataclass
class Transcript:
    text: str
    # Длительность записи по данным декодера — для лога и лимитов.
    duration_sec: float = 0.0


class STTProvider(Protocol):
    name: str

    async def transcribe(self, audio: bytes, *, content_type: str) -> Transcript:
        """Байты записи из браузера → текст. Формат определяет декодер."""
        ...

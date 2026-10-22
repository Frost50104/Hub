"""Провайдеры расшифровки длинных файлов: локальный STT-юнит кусками и
OpenAI-совместимый удалённый Whisper. Общие типы и чистая математика —
`base.py`. Выбор — `get_provider(settings)`; без настройки → None (задание
падает финально `stt_not_configured`, здоровье показывает код)."""

from __future__ import annotations

from typing import Any

from app.config import Settings


def get_provider(settings: Settings) -> Any | None:
    if settings.media_stt_provider == "openai":
        if not (settings.media_stt_api_key and settings.media_stt_base_url):
            return None
        from app.services.media.transcription.openai_compat import OpenAICompatProvider

        return OpenAICompatProvider(
            api_key=settings.media_stt_api_key,
            base_url=settings.media_stt_base_url,
            model=settings.media_stt_model,
        )
    if not settings.media_stt_url:
        return None
    from app.services.media.transcription.local_unit import LocalUnitProvider

    return LocalUnitProvider(
        base_url=settings.media_stt_url,
        model=f"faster-whisper/{settings.stt_model}",
        chunk_sec=settings.media_stt_chunk_sec,
        pause_sec=settings.media_stt_pause_sec,
    )

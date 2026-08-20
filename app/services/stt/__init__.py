"""Фабрика STT-провайдера."""

from __future__ import annotations

from app.config import get_settings
from app.services.stt.base import (
    STTError,
    STTNotConfigured,
    STTProvider,
    Transcript,
)

__all__ = ["STTError", "STTNotConfigured", "STTProvider", "Transcript", "get_stt"]


def get_stt() -> STTProvider:
    """Провайдер для процесса, который РЕАЛЬНО считает (stt_service).

    Основное приложение сюда не ходит: для `local` оно проксирует запрос в
    отдельный юнит, чтобы веса модели не жили в API-процессе.
    """
    s = get_settings()
    if not s.stt_enabled:
        raise STTNotConfigured("Голосовой ввод выключен (SIGNARIS_HUB_STT_ENABLED)")
    if s.stt_provider == "local":
        from app.services.stt.local import LocalWhisper

        return LocalWhisper()
    if s.stt_provider == "openai":
        if not s.stt_api_key or not s.stt_base_url:
            raise STTNotConfigured(
                "Для STT-провайдера openai нужны SIGNARIS_HUB_STT_API_KEY и _BASE_URL"
            )
        from app.services.stt.openai_compat import OpenAICompatSTT

        return OpenAICompatSTT(
            api_key=s.stt_api_key,
            base_url=s.stt_base_url,
            model=s.stt_model,
        )
    raise STTNotConfigured(f"Неизвестный STT-провайдер: {s.stt_provider!r}")

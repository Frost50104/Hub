"""Фабрика LLM-провайдера (Ф6): выбор конфигом, без ключа — LLMNotConfigured."""

from __future__ import annotations

from functools import lru_cache

from app.config import get_settings
from app.services.llm.base import (
    ChatMessage,
    LLMEmbeddingsUnsupported,
    LLMError,
    LLMNotConfigured,
    LLMProvider,
)

__all__ = [
    "ChatMessage",
    "LLMEmbeddingsUnsupported",
    "LLMError",
    "LLMNotConfigured",
    "LLMProvider",
    "get_provider",
]


@lru_cache(maxsize=1)
def get_provider() -> LLMProvider:
    settings = get_settings()
    if not settings.ai_enabled or not settings.ai_api_key:
        raise LLMNotConfigured(
            "AI-помощник не настроен: задайте SIGNARIS_HUB_AI_API_KEY "
            "(+ SIGNARIS_HUB_AI_PROVIDER / _FOLDER_ID / _BASE_URL)"
        )
    provider = settings.ai_provider
    if provider == "yandex":
        if not settings.ai_folder_id:
            raise LLMNotConfigured("Для YandexGPT нужен SIGNARIS_HUB_AI_FOLDER_ID")
        from app.services.llm.yandex import YandexProvider

        return YandexProvider(
            api_key=settings.ai_api_key,
            folder_id=settings.ai_folder_id,
            chat_model=settings.ai_chat_model,
            embed_model=settings.ai_embed_model,
        )
    if provider == "gigachat":
        from app.services.llm.gigachat import GigaChatProvider

        return GigaChatProvider(
            api_key=settings.ai_api_key,
            chat_model=settings.ai_chat_model,
            embed_model=settings.ai_embed_model,
        )
    if provider == "openai":
        if not settings.ai_base_url:
            raise LLMNotConfigured("Для OpenAI-compatible нужен SIGNARIS_HUB_AI_BASE_URL")
        from app.services.llm.openai_compat import OpenAICompatProvider

        return OpenAICompatProvider(
            api_key=settings.ai_api_key,
            base_url=settings.ai_base_url,
            chat_model=settings.ai_chat_model,
            embed_model=settings.ai_embed_model,
        )
    raise LLMNotConfigured(f"Неизвестный AI-провайдер: {provider!r}")

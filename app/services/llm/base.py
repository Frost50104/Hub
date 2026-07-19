"""LLM-абстракция (Ф6): embed + chat, переключение провайдера конфигом.

Решение пользователя: первый провайдер — YandexGPT/GigaChat, но интерфейс
обязан позволять переезд на OpenAI/Mistral/DeepSeek без правок кода —
поэтому третий провайдер `openai` говорит на OpenAI-compatible API и
покрывает всех совместимых (меняются только base_url/model/key).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class LLMError(RuntimeError):
    """Ошибка провайдера (сеть/квота/авторизация) — API мапит в 502."""


class LLMNotConfigured(RuntimeError):
    """Ассистент выключен или нет ключа — API мапит в 503."""


@dataclass
class ChatMessage:
    role: str  # system | user | assistant
    content: str


class LLMProvider(Protocol):
    """Единый контракт: провайдер умеет эмбеддинги и чат."""

    name: str
    embed_model: str

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Эмбеддинги пачки текстов (порядок сохраняется)."""
        ...

    async def chat(self, messages: list[ChatMessage]) -> str:
        """Ответ модели на диалог (system+история+вопрос)."""
        ...

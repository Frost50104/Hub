"""LLM-абстракция (Ф6): embed + chat, переключение провайдера конфигом.

Решение пользователя: первый провайдер — YandexGPT/GigaChat, но интерфейс
обязан позволять переезд на OpenAI/Mistral/DeepSeek без правок кода —
поэтому третий провайдер `openai` говорит на OpenAI-compatible API и
покрывает всех совместимых (меняются только base_url/model/key).

Ассистент (волна 1) добавил tool-calling: `chat_with_tools` умеет только
OpenAI-совместимый провайдер, остальные бросают `LLMToolsUnsupported` —
тем же приёмом, что `LLMEmbeddingsUnsupported`, чтобы смена провайдера
деградировала до read-only ассистента, а не роняла ручку.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


class LLMError(RuntimeError):
    """Ошибка провайдера (сеть/квота/авторизация) — API мапит в 502."""


class LLMEmbeddingsUnsupported(LLMError):
    """Провайдер без embeddings API (DeepSeek): retrieval падает на
    лексический поиск по search_documents, воркер пропускает RAG-шаг."""


class LLMToolsUnsupported(LLMError):
    """Провайдер без function-calling: ассистент отвечает без инструментов
    (read-only RAG по базе знаний), действий не предлагает."""


class LLMNotConfigured(RuntimeError):
    """Ассистент выключен или нет ключа — API мапит в 503."""


@dataclass
class ToolSpec:
    """Описание инструмента для модели. `parameters` — JSON Schema объекта."""

    name: str
    description: str
    parameters: dict[str, Any]


@dataclass
class ToolCall:
    """Запрос модели вызвать инструмент. `arguments` уже распарсены из JSON."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ChatMessage:
    # system | user | assistant | tool
    role: str
    content: str
    # role=assistant: что модель попросила вызвать на прошлом витке.
    tool_calls: list[ToolCall] = field(default_factory=list)
    # role=tool: к какому вызову относится этот результат.
    tool_call_id: str | None = None


@dataclass
class ChatResult:
    """Ответ модели: текст и/или запрошенные вызовы инструментов."""

    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)


class LLMProvider(Protocol):
    """Единый контракт: провайдер умеет эмбеддинги и чат."""

    name: str
    embed_model: str
    # Умеет ли вызывать инструменты. Спрашивается ДО обращения к сети:
    # экран ассистента должен знать, показывать ли подсказки про действия,
    # не тратя запрос к модели.
    supports_tools: bool

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Эмбеддинги пачки текстов (порядок сохраняется)."""
        ...

    async def chat(self, messages: list[ChatMessage]) -> str:
        """Ответ модели на диалог (system+история+вопрос)."""
        ...

    async def chat_with_tools(
        self, messages: list[ChatMessage], tools: list[ToolSpec]
    ) -> ChatResult:
        """Виток с инструментами. `LLMToolsUnsupported` — если не умеет."""
        ...

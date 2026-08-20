"""OpenAI-compatible провайдер: OpenAI, Mistral, DeepSeek, локальные прокси.

Меняются только base_url / api_key / модели — код один. Примеры base_url:
OpenAI https://api.openai.com/v1, DeepSeek https://api.deepseek.com/v1,
Mistral https://api.mistral.ai/v1.

Прод Hub'а сидит на DeepSeek. Проверено 2026-08-20 на живом API: и flash, и
pro отдают корректный tool_calls с кириллицей в аргументах, второй виток
(результат инструмента ролью `tool`) принимается без нареканий.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from app.services.llm.base import (
    ChatMessage,
    ChatResult,
    LLMEmbeddingsUnsupported,
    LLMError,
    ToolCall,
    ToolSpec,
)


def _dump_message(m: ChatMessage) -> dict[str, Any]:
    """ChatMessage → тело OpenAI. Ключи tool_calls/tool_call_id добавляются
    ТОЛЬКО когда заполнены: DeepSeek отвергает `tool_call_id: null`."""
    out: dict[str, Any] = {"role": m.role, "content": m.content}
    if m.tool_calls:
        out["tool_calls"] = [
            {
                "id": c.id,
                "type": "function",
                "function": {
                    "name": c.name,
                    "arguments": json.dumps(c.arguments, ensure_ascii=False),
                },
            }
            for c in m.tool_calls
        ]
    if m.tool_call_id:
        out["tool_call_id"] = m.tool_call_id
    return out


def _parse_tool_calls(raw: list[dict[str, Any]] | None) -> list[ToolCall]:
    """tool_calls из ответа. Невалидный JSON аргументов НЕ роняет виток:
    инструмент получит пустые args и сам ответит ошибкой валидации —
    так модель видит причину и может переспросить."""
    calls: list[ToolCall] = []
    for c in raw or []:
        fn = c.get("function") or {}
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except (TypeError, ValueError):
            args = {}
        if not isinstance(args, dict):
            args = {}
        calls.append(
            ToolCall(
                id=str(c.get("id") or ""),
                name=str(fn.get("name") or ""),
                arguments=args,
            )
        )
    return calls


class OpenAICompatProvider:
    name = "openai"
    supports_tools = True

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        chat_model: str | None = None,
        embed_model: str | None = None,
        tool_model: str | None = None,
    ) -> None:
        self._api_key = api_key
        self._base = base_url.rstrip("/")
        self._chat_model = chat_model or "gpt-4o-mini"
        # Витки с инструментами можно увести на более сильную модель, не
        # трогая обычные ответы по базе знаний.
        self._tool_model = tool_model or self._chat_model
        self._embed = embed_model or "text-embedding-3-small"
        self.embed_model = f"openai:{self._embed}"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"}

    async def embed(self, texts: list[str]) -> list[list[float]]:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{self._base}/embeddings",
                headers=self._headers(),
                json={"model": self._embed, "input": [t[:8000] for t in texts]},
            )
        if resp.status_code == 404:
            # DeepSeek и часть совместимых не дают embeddings — ассистент
            # работает через лексический retrieval.
            raise LLMEmbeddingsUnsupported(
                f"{self._base} не поддерживает /embeddings"
            )
        if resp.status_code != 200:
            raise LLMError(f"openai embed {resp.status_code}: {resp.text[:200]}")
        rows = sorted(resp.json()["data"], key=lambda d: d["index"])
        return [[float(x) for x in row["embedding"]] for row in rows]

    async def _post_chat(self, body: dict[str, Any], *, timeout: float) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{self._base}/chat/completions", headers=self._headers(), json=body
            )
        if resp.status_code != 200:
            raise LLMError(f"openai chat {resp.status_code}: {resp.text[:200]}")
        try:
            return resp.json()["choices"][0]["message"]
        except (KeyError, IndexError) as e:
            raise LLMError(f"openai chat: неожиданный ответ ({e})") from None

    async def chat(self, messages: list[ChatMessage]) -> str:
        msg = await self._post_chat(
            {
                "model": self._chat_model,
                "temperature": 0.2,
                "messages": [_dump_message(m) for m in messages],
            },
            timeout=90,
        )
        return msg.get("content") or ""

    async def chat_with_tools(
        self, messages: list[ChatMessage], tools: list[ToolSpec]
    ) -> ChatResult:
        # Таймаут ниже nginx-лимита локации /api/ai/ и укладывается в бюджет
        # витков в runner'е: лучше честная ошибка, чем 504 от прокси.
        msg = await self._post_chat(
            {
                "model": self._tool_model,
                "temperature": 0.2,
                "messages": [_dump_message(m) for m in messages],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": t.name,
                            "description": t.description,
                            "parameters": t.parameters,
                        },
                    }
                    for t in tools
                ],
            },
            timeout=60,
        )
        return ChatResult(
            content=msg.get("content") or "",
            tool_calls=_parse_tool_calls(msg.get("tool_calls")),
        )

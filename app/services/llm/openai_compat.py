"""OpenAI-compatible провайдер: OpenAI, Mistral, DeepSeek, локальные прокси.

Меняются только base_url / api_key / модели — код один. Примеры base_url:
OpenAI https://api.openai.com/v1, DeepSeek https://api.deepseek.com/v1,
Mistral https://api.mistral.ai/v1.
"""

from __future__ import annotations

import httpx

from app.services.llm.base import ChatMessage, LLMEmbeddingsUnsupported, LLMError


class OpenAICompatProvider:
    name = "openai"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        chat_model: str | None = None,
        embed_model: str | None = None,
    ) -> None:
        self._api_key = api_key
        self._base = base_url.rstrip("/")
        self._chat_model = chat_model or "gpt-4o-mini"
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

    async def chat(self, messages: list[ChatMessage]) -> str:
        async with httpx.AsyncClient(timeout=90) as client:
            resp = await client.post(
                f"{self._base}/chat/completions",
                headers=self._headers(),
                json={
                    "model": self._chat_model,
                    "temperature": 0.2,
                    "messages": [{"role": m.role, "content": m.content} for m in messages],
                },
            )
        if resp.status_code != 200:
            raise LLMError(f"openai chat {resp.status_code}: {resp.text[:200]}")
        try:
            return resp.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise LLMError(f"openai chat: неожиданный ответ ({e})") from None

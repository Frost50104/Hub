"""YandexGPT (Foundation Models API): completion + textEmbedding.

Auth: Api-Key (сервисный аккаунт с ролью ai.languageModels.user);
модели адресуются URI gpt://{folder_id}/{model}. Эмбеддинги — 256-мерные
text-search-doc/query.
"""

from __future__ import annotations

import asyncio

import httpx
import structlog

from app.services.llm.base import ChatMessage, LLMError

log = structlog.get_logger("llm.yandex")

_BASE = "https://llm.api.cloud.yandex.net/foundationModels/v1"


class YandexProvider:
    name = "yandex"

    def __init__(
        self,
        *,
        api_key: str,
        folder_id: str,
        chat_model: str | None = None,
        embed_model: str | None = None,
    ) -> None:
        self._api_key = api_key
        self._folder_id = folder_id
        self._chat_uri = f"gpt://{folder_id}/{chat_model or 'yandexgpt-lite/latest'}"
        self._embed_doc_uri = f"emb://{folder_id}/{embed_model or 'text-search-doc/latest'}"
        self.embed_model = f"yandex:{embed_model or 'text-search-doc'}"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Api-Key {self._api_key}",
            "x-folder-id": self._folder_id,
        }

    async def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        async with httpx.AsyncClient(timeout=30) as client:
            for text in texts:
                resp = await client.post(
                    f"{_BASE}/textEmbedding",
                    headers=self._headers(),
                    json={"modelUri": self._embed_doc_uri, "text": text[:8000]},
                )
                if resp.status_code != 200:
                    raise LLMError(f"yandex embed {resp.status_code}: {resp.text[:200]}")
                out.append([float(x) for x in resp.json()["embedding"]])
                await asyncio.sleep(0.05)  # бесплатный tier чувствителен к RPS
        return out

    async def chat(self, messages: list[ChatMessage]) -> str:
        payload = {
            "modelUri": self._chat_uri,
            "completionOptions": {"stream": False, "temperature": 0.2, "maxTokens": "1500"},
            "messages": [
                {"role": m.role if m.role != "system" else "system", "text": m.content}
                for m in messages
            ],
        }
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{_BASE}/completion", headers=self._headers(), json=payload
            )
        if resp.status_code != 200:
            raise LLMError(f"yandex chat {resp.status_code}: {resp.text[:200]}")
        try:
            return resp.json()["result"]["alternatives"][0]["message"]["text"]
        except (KeyError, IndexError) as e:
            raise LLMError(f"yandex chat: неожиданный ответ ({e})") from None

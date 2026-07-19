"""GigaChat (Сбер): OAuth client-credentials + chat/completions + embeddings.

api_key = Authorization key (base64 client_id:secret) из личного кабинета.
Токен живёт ~30 мин — кэшируется и обновляется по 401. НГЛУ-сертификаты
Минцифры: verify отключён осознанно (стандартная боль GigaChat API;
альтернатива — руками ставить russian_trusted_root_ca в системное хранилище).
"""

from __future__ import annotations

import time
import uuid

import httpx
import structlog

from app.services.llm.base import ChatMessage, LLMError

log = structlog.get_logger("llm.gigachat")

_OAUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
_API_BASE = "https://gigachat.devices.sberbank.ru/api/v1"


class GigaChatProvider:
    name = "gigachat"

    def __init__(
        self,
        *,
        api_key: str,
        chat_model: str | None = None,
        embed_model: str | None = None,
    ) -> None:
        self._auth_key = api_key
        self._chat_model = chat_model or "GigaChat"
        self._embed = embed_model or "Embeddings"
        self.embed_model = f"gigachat:{self._embed}"
        self._token: str | None = None
        self._token_exp: float = 0

    async def _access_token(self) -> str:
        if self._token and time.time() < self._token_exp - 60:
            return self._token
        async with httpx.AsyncClient(timeout=30, verify=False) as client:  # noqa: S501
            resp = await client.post(
                _OAUTH_URL,
                headers={
                    "Authorization": f"Basic {self._auth_key}",
                    "RqUID": str(uuid.uuid4()),
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={"scope": "GIGACHAT_API_PERS"},
            )
        if resp.status_code != 200:
            raise LLMError(f"gigachat oauth {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        self._token = data["access_token"]
        self._token_exp = data.get("expires_at", (time.time() + 1700) * 1000) / 1000
        return self._token

    async def embed(self, texts: list[str]) -> list[list[float]]:
        token = await self._access_token()
        async with httpx.AsyncClient(timeout=60, verify=False) as client:  # noqa: S501
            resp = await client.post(
                f"{_API_BASE}/embeddings",
                headers={"Authorization": f"Bearer {token}"},
                json={"model": self._embed, "input": [t[:8000] for t in texts]},
            )
        if resp.status_code != 200:
            raise LLMError(f"gigachat embed {resp.status_code}: {resp.text[:200]}")
        rows = sorted(resp.json()["data"], key=lambda d: d["index"])
        return [[float(x) for x in row["embedding"]] for row in rows]

    async def chat(self, messages: list[ChatMessage]) -> str:
        token = await self._access_token()
        async with httpx.AsyncClient(timeout=90, verify=False) as client:  # noqa: S501
            resp = await client.post(
                f"{_API_BASE}/chat/completions",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "model": self._chat_model,
                    "temperature": 0.2,
                    "messages": [{"role": m.role, "content": m.content} for m in messages],
                },
            )
        if resp.status_code != 200:
            raise LLMError(f"gigachat chat {resp.status_code}: {resp.text[:200]}")
        try:
            return resp.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise LLMError(f"gigachat chat: неожиданный ответ ({e})") from None

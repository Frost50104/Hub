"""OpenAI-совместимый `/audio/transcriptions` — платная альтернатива.

Нужна там, где локальную модель держать негде: включается одной переменной
`SIGNARIS_HUB_STT_PROVIDER=openai` плюс ключ и base_url.
"""

from __future__ import annotations

import httpx

from app.services.stt.base import STTError, Transcript


class OpenAICompatSTT:
    name = "openai"

    def __init__(self, *, api_key: str, base_url: str, model: str) -> None:
        self._key = api_key
        self._base = base_url.rstrip("/")
        self._model = model

    async def transcribe(self, audio: bytes, *, content_type: str) -> Transcript:
        async with httpx.AsyncClient(timeout=90) as client:
            resp = await client.post(
                f"{self._base}/audio/transcriptions",
                headers={"Authorization": f"Bearer {self._key}"},
                files={"file": ("audio", audio, content_type)},
                data={"model": self._model, "language": "ru"},
            )
        if resp.status_code != 200:
            raise STTError(f"STT {resp.status_code}: {resp.text[:200]}")
        try:
            return Transcript(text=str(resp.json()["text"]).strip())
        except (KeyError, ValueError) as e:
            raise STTError(f"STT: неожиданный ответ ({e})") from None

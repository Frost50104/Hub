"""Клиент Hedra v3 (Character-3) — три ручки и поллинг, транспорт инжектится
(`httpx.MockTransport` в тестах). Политика ошибок — решение плана:

- 429 → сон по `Retry-After` (≤ 120 с), это не попытка;
- 5xx и сеть → экспоненциально, три раза;
- 402 → `insufficient_balance` («Пополните баланс Hedra»), 422 → `moderation_failed`,
  400 → `invalid_argument`, 401/403 → `hedra_auth` — финальные, без повтора;
- presigned URL результата истекает — скачивать СРАЗУ, handle загруженного
  файла живёт ~1 ч — грузить аудио непосредственно перед submit.

Повторная отправка того же куска идёт с тем же `idempotency_key`, поэтому
возобновлённое после рестарта задание не платит дважды.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import structlog

log = structlog.get_logger("media.hedra")

MODEL_ID = "hedra-character-3"
RETRY_ERR_SEC = (3.0, 10.0, 30.0)
MAX_RETRY_AFTER_SEC = 120.0
MAX_DURATION_MS = 600_000


class HedraError(RuntimeError):
    def __init__(self, code: str, message: str = "", *, final: bool = True) -> None:
        super().__init__(f"{code}: {message}" if message else code)
        self.code = code
        self.message = message
        self.final = final


@dataclass(frozen=True)
class HedraJob:
    job_id: str
    status: str
    progress: float | None = None
    error: str | None = None
    output_url: str | None = None
    cost: float | None = None
    duration_ms: int | None = None


def _status_of(data: dict[str, Any]) -> str:
    raw = str(data.get("status") or data.get("state") or "").lower()
    if raw in ("complete", "completed", "succeeded", "success", "done"):
        return "complete"
    if raw in ("error", "failed", "failure", "cancelled", "canceled"):
        return "error"
    return raw or "queued"


def parse_job(data: dict[str, Any]) -> HedraJob:
    """Ответ `GET /v3/jobs/{id}` или `/status` → наша форма. Поля Hedra
    различаются версией API — читаем снисходительно."""
    outputs = data.get("outputs") or data.get("asset") or []
    output_url: str | None = None
    if isinstance(outputs, list):
        for item in outputs:
            if isinstance(item, dict) and item.get("url"):
                output_url = str(item["url"])
                break
    elif isinstance(outputs, dict) and outputs.get("url"):
        output_url = str(outputs["url"])
    if output_url is None and isinstance(data.get("asset"), dict):
        asset = data["asset"].get("asset") or {}
        if isinstance(asset, dict) and asset.get("url"):
            output_url = str(asset["url"])
    cost_raw = data.get("cost") or data.get("credits") or (data.get("billing") or {}).get("cost")
    try:
        cost = float(cost_raw) if cost_raw is not None else None
    except (TypeError, ValueError):
        cost = None
    duration = data.get("duration_ms")
    try:
        duration_ms = int(duration) if duration is not None else None
    except (TypeError, ValueError):
        duration_ms = None
    progress = data.get("progress")
    try:
        progress_f = float(progress) if progress is not None else None
    except (TypeError, ValueError):
        progress_f = None
    error = data.get("error_message") or data.get("error") or None
    return HedraJob(
        job_id=str(data.get("id") or data.get("job_id") or ""),
        status=_status_of(data),
        progress=progress_f,
        error=str(error) if error else None,
        output_url=output_url,
        cost=cost,
        duration_ms=duration_ms,
    )


class HedraClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.hedra.com/v3",
        timeout_sec: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_sec = timeout_sec
        self._transport = transport
        self._sleep = sleep

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url,
            headers={"X-API-Key": self._key},
            timeout=self.timeout_sec,
            transport=self._transport,
        )

    async def _request(self, method: str, path: str, **kw: Any) -> dict[str, Any]:
        err_waits = 0
        async with self._client() as client:
            while True:
                try:
                    resp = await client.request(method, path, **kw)
                except httpx.HTTPError as exc:
                    if err_waits >= len(RETRY_ERR_SEC):
                        raise HedraError(
                            "hedra_unreachable", type(exc).__name__, final=False
                        ) from exc
                    await self._sleep(RETRY_ERR_SEC[err_waits])
                    err_waits += 1
                    continue
                if resp.status_code == 429:
                    retry_after = resp.headers.get("Retry-After")
                    try:
                        wait = min(MAX_RETRY_AFTER_SEC, float(retry_after)) if retry_after else 30.0
                    except ValueError:
                        wait = 30.0
                    log.info("media.hedra_rate_limited", wait_sec=wait)
                    await self._sleep(wait)
                    continue
                if resp.status_code >= 500:
                    if err_waits >= len(RETRY_ERR_SEC):
                        raise HedraError(
                            "hedra_error", f"{resp.status_code} {resp.text[:200]}", final=False
                        )
                    await self._sleep(RETRY_ERR_SEC[err_waits])
                    err_waits += 1
                    continue
                if resp.status_code in (401, 403):
                    raise HedraError("hedra_auth", resp.text[:200])
                if resp.status_code == 402:
                    raise HedraError("insufficient_balance", resp.text[:200])
                if resp.status_code == 422:
                    raise HedraError("moderation_failed", resp.text[:300])
                if resp.status_code == 400:
                    raise HedraError("invalid_argument", resp.text[:300])
                if resp.status_code >= 300:
                    raise HedraError("hedra_error", f"{resp.status_code} {resp.text[:200]}")
                if resp.status_code == 204 or not resp.content:
                    return {}
                try:
                    data = resp.json()
                except ValueError as exc:
                    raise HedraError("hedra_bad_response", str(exc)[:100]) from None
                return data if isinstance(data, dict) else {"data": data}

    async def upload_file(self, path: Path, *, purpose: str, mime: str) -> str:
        """`POST /v3/files` → `id` (handle, живёт ~1 ч)."""
        with path.open("rb") as fh:
            data = await self._request(
                "POST",
                "/files",
                files={"file": (path.name, fh, mime)},
                data={"purpose": purpose},
            )
        file_id = data.get("id") or data.get("file_id") or (data.get("file") or {}).get("id")
        if not file_id:
            raise HedraError("hedra_bad_response", "у загруженного файла нет id")
        return str(file_id)

    async def submit(
        self,
        *,
        image_id: str,
        audio_id: str,
        resolution: str,
        duration_ms: int,
        idempotency_key: str,
        prompt: str = "",
        aspect_ratio: str = "16:9",
    ) -> str:
        """`POST /v3/models/hedra-character-3` → `job_id` (202)."""
        if duration_ms > MAX_DURATION_MS:
            raise HedraError("invalid_argument", f"кусок длиннее {MAX_DURATION_MS // 1000} с")
        body = {
            "input": {
                "prompt": prompt,
                "aspect_ratio": aspect_ratio,
                "resolution": resolution,
                "start_image": {"source": "file", "id": image_id},
                "audio": {"source": "file", "id": audio_id},
                "duration_ms": duration_ms,
            },
            "idempotency_key": idempotency_key,
        }
        data = await self._request("POST", f"/models/{MODEL_ID}", json=body)
        job_id = data.get("id") or data.get("job_id")
        if not job_id:
            raise HedraError("hedra_bad_response", "в ответе нет id задания")
        return str(job_id)

    async def estimate(self, *, resolution: str, duration_ms: int) -> dict[str, Any] | None:
        """Сверка цены с Hedra — best-effort: любая ошибка → None, локальная
        таблица цен авторитетна."""
        try:
            return await self._request(
                "POST",
                f"/models/{MODEL_ID}/estimate",
                json={
                    "input": {
                        "resolution": resolution,
                        "duration_ms": duration_ms,
                        "aspect_ratio": "16:9",
                    }
                },
            )
        except HedraError:
            return None

    async def status(self, job_id: str) -> HedraJob:
        return parse_job(await self._request("GET", f"/jobs/{job_id}/status"))

    async def job(self, job_id: str) -> HedraJob:
        return parse_job(await self._request("GET", f"/jobs/{job_id}"))

    async def wait(
        self,
        job_id: str,
        *,
        poll_sec: float,
        max_wait_sec: float,
        on_tick: Callable[[HedraJob], Awaitable[None]] | None = None,
        cancel: asyncio.Event | None = None,
    ) -> HedraJob:
        """Поллинг до `complete`/`error` с потолком. `cancel` — выйти без
        результата (задание Hedra продолжит жить, минуты уже списаны)."""
        waited = 0.0
        while True:
            if cancel is not None and cancel.is_set():
                raise HedraError("cancelled", final=True)
            job = await self.status(job_id)
            if on_tick is not None:
                await on_tick(job)
            if job.status == "complete":
                full = await self.job(job_id)
                return full if full.output_url else job
            if job.status == "error":
                raise HedraError("hedra_job_failed", job.error or "без описания")
            if waited >= max_wait_sec:
                raise HedraError(
                    "hedra_timeout", f"нет результата за {int(max_wait_sec)} с", final=False
                )
            await self._sleep(poll_sec)
            waited += poll_sec

    async def download(self, url: str, dest: Path) -> int:
        """Скачать результат по presigned URL (истекает — зовётся сразу)."""
        async with (
            httpx.AsyncClient(timeout=self.timeout_sec, transport=self._transport) as client,
            client.stream("GET", url) as resp,
        ):
            if resp.status_code != 200:
                raise HedraError("hedra_download", f"{resp.status_code}", final=False)
            size = 0
            with dest.open("wb") as fh:
                async for chunk in resp.aiter_bytes():
                    fh.write(chunk)
                    size += len(chunk)
        return size

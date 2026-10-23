"""Клиент Hedra v3 (Character-3) — три ручки и поллинг, транспорт инжектится
(`httpx.MockTransport` в тестах). Форма API сверена с `api.hedra.com/v3/openapi.json`
на первом живом прогоне 23.10:

- `POST /v3/files` (multipart `file`) → `{url, content_type, expires_at}` — presigned
  `url` И ЕСТЬ handle: в submit он уходит как `{"source": "url", "url": …}` побайтово,
  живёт ~1 ч (просроченный → 400 `reason: "expired"`), поэтому сцена и голос грузятся
  непосредственно перед КАЖДЫМ submit;
- `POST /v3/models/hedra-character-3` `{input: {prompt, aspect_ratio, resolution,
  duration_ms, start_image, audio}}` → 202 `{job_id, status}`; лишние поля тела —
  400, идемпотентности у API нет (`Idempotency-Key` шлём заголовком на будущее,
  от двойной оплаты защищает наша запись `job_id` сразу после submit);
- `GET /v3/jobs/{id}/status` → `{job_id, status, progress 0..1}`, статусы
  `IN_QUEUE | IN_PROGRESS | COMPLETED | FAILED`; `GET /v3/jobs/{id}` → `outputs[].url`
  (presigned, истекает — скачивать СРАЗУ), `cost`, `error: {code, message}`.

Политика ошибок — решение плана: 429 → сон по `Retry-After` (≤ 120 с), это не
попытка; 5xx и сеть → экспоненциально, три раза; `INSUFFICIENT_BALANCE`/402 →
`insufficient_balance`, `MODERATION_FAILED`/422 → `moderation_failed`,
`INVALID_ARGUMENT`/400 → `invalid_argument`, 401/403 → `hedra_auth` — финальные.
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
    error_raw = data.get("error_message") or data.get("error") or None
    if isinstance(error_raw, dict):
        code, message = error_raw.get("code"), error_raw.get("message")
        error = f"{code}: {message}" if code and message else str(message or code or "")
    else:
        error = str(error_raw) if error_raw else ""
    return HedraJob(
        job_id=str(data.get("job_id") or data.get("id") or ""),
        status=_status_of(data),
        progress=progress_f,
        error=error or None,
        output_url=output_url,
        cost=cost,
        duration_ms=duration_ms,
    )


def media_ref(ref: str) -> dict[str, str]:
    """Ссылка на медиа в `input`: presigned url от `POST /v3/files` или
    `asset_<uuid>` готового выхода — `source` выбирается по форме."""
    if ref.startswith(("http://", "https://")):
        return {"source": "url", "url": ref}
    return {"source": "asset", "asset_id": ref}


# Код ошибки Hedra (`error.code` в теле) → наш код; статус HTTP — запасной путь.
_CODE_MAP: dict[str, str] = {
    "INSUFFICIENT_BALANCE": "insufficient_balance",
    "MODERATION_FAILED": "moderation_failed",
    "UNAUTHORIZED": "hedra_auth",
    "PERMISSION_DENIED": "hedra_auth",
    "INVALID_ARGUMENT": "invalid_argument",
    "FAILED_PRECONDITION": "invalid_argument",
    "NOT_FOUND": "invalid_argument",
    "GONE": "invalid_argument",
}
_STATUS_MAP: dict[int, str] = {
    400: "invalid_argument",
    401: "hedra_auth",
    402: "insufficient_balance",
    403: "hedra_auth",
    404: "invalid_argument",
    422: "moderation_failed",
}


def _error_of(resp: httpx.Response) -> HedraError:
    """Финальная ошибка из ответа 3xx/4xx: код из конверта `{"error": {code,
    message}}`, иначе по статусу; текст — `message` конверта, иначе хвост тела."""
    code: str | None = None
    message = resp.text[:300]
    try:
        body = resp.json()
    except ValueError:
        body = None
    env = body.get("error") if isinstance(body, dict) else None
    if isinstance(env, dict):
        raw = str(env.get("code") or "").upper()
        code = _CODE_MAP.get(raw)
        if env.get("message"):
            message = f"{raw}: {env['message']}"[:300] if raw else str(env["message"])[:300]
    if code is None:
        code = _STATUS_MAP.get(resp.status_code, "hedra_error")
    if code == "hedra_error":
        message = f"{resp.status_code} {message[:200]}"
    return HedraError(code, message)


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
                if resp.status_code >= 300:
                    raise _error_of(resp)
                if resp.status_code == 204 or not resp.content:
                    return {}
                try:
                    data = resp.json()
                except ValueError as exc:
                    raise HedraError("hedra_bad_response", str(exc)[:100]) from None
                return data if isinstance(data, dict) else {"data": data}

    async def upload_file(self, path: Path, *, purpose: str, mime: str) -> str:
        """`POST /v3/files` → handle: presigned `url` (живёт ~1 ч, передаётся в
        submit побайтово). `purpose` API не принимает — остаётся в сигнатуре
        для логов вызывающего; тип сервер сниффит по байтам сам."""
        with path.open("rb") as fh:
            data = await self._request(
                "POST",
                "/files",
                files={"file": (path.name, fh, mime)},
            )
        handle = data.get("url") or data.get("id") or data.get("file_id")
        if not handle:
            raise HedraError("hedra_bad_response", f"у загруженного файла ({purpose}) нет url")
        return str(handle)

    async def submit(
        self,
        *,
        image_ref: str,
        audio_ref: str,
        resolution: str,
        duration_ms: int,
        idempotency_key: str,
        prompt: str = "",
        aspect_ratio: str = "16:9",
    ) -> str:
        """`POST /v3/models/hedra-character-3` → `job_id` (202). `*_ref` — handle
        из `upload_file` (url) либо `asset_<uuid>` готового выхода Hedra."""
        if duration_ms > MAX_DURATION_MS:
            raise HedraError("invalid_argument", f"кусок длиннее {MAX_DURATION_MS // 1000} с")
        body = {
            "input": {
                "prompt": prompt,
                "aspect_ratio": aspect_ratio,
                "resolution": resolution,
                "start_image": media_ref(image_ref),
                "audio": media_ref(audio_ref),
                "duration_ms": duration_ms,
            },
        }
        data = await self._request(
            "POST",
            f"/models/{MODEL_ID}",
            json=body,
            headers={"Idempotency-Key": idempotency_key},
        )
        job_id = data.get("job_id") or data.get("id")
        if not job_id:
            raise HedraError("hedra_bad_response", "в ответе нет job_id")
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

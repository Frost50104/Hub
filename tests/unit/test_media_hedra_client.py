"""Клиент Hedra на MockTransport: заголовок ключа, тело submit с
idempotency_key, 429 по Retry-After (не попытка), финальные 402/422/401,
повторы 5xx, поллинг до результата, скачивание сразу."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from app.services.media.hedra.client import HedraClient, HedraError, parse_job


def _client(handler, sleeps: list[float] | None = None) -> HedraClient:
    async def fake_sleep(sec: float) -> None:
        if sleeps is not None:
            sleeps.append(sec)

    return HedraClient(
        api_key="k",
        base_url="https://api.hedra.com/v3/",
        transport=httpx.MockTransport(handler),
        sleep=fake_sleep,
    )


async def test_upload_submit_and_headers(tmp_path: Path):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/v3/files":
            assert request.headers["x-api-key"] == "k"
            return httpx.Response(200, json={"id": "file_1"})
        if request.url.path == "/v3/models/hedra-character-3":
            body = json.loads(request.content)
            assert body["idempotency_key"] == "job:0"
            assert body["input"]["start_image"] == {"source": "file", "id": "img"}
            assert body["input"]["audio"] == {"source": "file", "id": "file_1"}
            assert body["input"]["resolution"] == "720p" and body["input"]["duration_ms"] == 30000
            return httpx.Response(202, json={"id": "gen_42", "status": "queued"})
        return httpx.Response(404)

    wav = tmp_path / "a.mp3"
    wav.write_bytes(b"\x00" * 16)
    client = _client(handler)
    file_id = await client.upload_file(wav, purpose="audio", mime="audio/mpeg")
    assert file_id == "file_1"
    job_id = await client.submit(
        image_id="img",
        audio_id=file_id,
        resolution="720p",
        duration_ms=30000,
        idempotency_key="job:0",
    )
    assert job_id == "gen_42"
    assert b'name="purpose"' in seen[0].content
    with pytest.raises(HedraError) as exc:
        await client.submit(
            image_id="i", audio_id="a", resolution="720p", duration_ms=700_000, idempotency_key="x"
        )
    assert exc.value.code == "invalid_argument"


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (402, "insufficient_balance"),
        (422, "moderation_failed"),
        (401, "hedra_auth"),
        (400, "invalid_argument"),
    ],
)
async def test_final_errors_do_not_retry(status, code):
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status, text="nope")

    with pytest.raises(HedraError) as exc:
        await _client(handler).status("j")
    assert exc.value.code == code and exc.value.final
    assert calls == 1


async def test_rate_limit_sleeps_by_retry_after_and_5xx_retries():
    sleeps: list[float] = []
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "7"})
        if calls == 2:
            return httpx.Response(503, text="busy")
        return httpx.Response(200, json={"id": "j", "status": "processing", "progress": 0.4})

    job = await _client(handler, sleeps).status("j")
    assert job.status == "processing" and job.progress == 0.4
    assert sleeps == [7.0, 3.0]

    sleeps.clear()
    with pytest.raises(HedraError) as exc:
        await _client(lambda r: httpx.Response(500), sleeps).status("j")
    assert exc.value.code == "hedra_error" and not exc.value.final
    assert sleeps == [3.0, 10.0, 30.0]


async def test_wait_polls_until_complete_and_fetches_output(tmp_path: Path):
    ticks = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal ticks
        if request.url.path == "/v3/jobs/j/status":
            ticks += 1
            return httpx.Response(
                200, json={"id": "j", "status": "processing" if ticks < 3 else "complete"}
            )
        if request.url.path == "/v3/jobs/j":
            return httpx.Response(
                200,
                json={
                    "id": "j",
                    "status": "complete",
                    "outputs": [{"url": "https://cdn/x.mp4"}],
                    "cost": 1.5,
                    "duration_ms": 30000,
                },
            )
        if request.url.host == "cdn":
            return httpx.Response(200, content=b"video-bytes")
        return httpx.Response(404)

    client = _client(handler, sleeps)
    seen: list[str] = []

    async def on_tick(job):
        seen.append(job.status)

    job = await client.wait("j", poll_sec=10, max_wait_sec=100, on_tick=on_tick)
    assert job.output_url == "https://cdn/x.mp4" and job.cost == 1.5 and job.duration_ms == 30000
    assert seen == ["processing", "processing", "complete"] and sleeps == [10.0, 10.0]
    dest = tmp_path / "out.mp4"
    assert await client.download(job.output_url, dest) == 11
    assert dest.read_bytes() == b"video-bytes"


async def test_wait_errors_and_timeout():
    with pytest.raises(HedraError) as exc:
        await _client(
            lambda r: httpx.Response(
                200, json={"id": "j", "status": "error", "error_message": "bad"}
            )
        ).wait("j", poll_sec=1, max_wait_sec=5)
    assert exc.value.code == "hedra_job_failed" and "bad" in str(exc.value)
    with pytest.raises(HedraError) as exc:
        await _client(
            lambda r: httpx.Response(200, json={"id": "j", "status": "processing"}), []
        ).wait("j", poll_sec=5, max_wait_sec=10)
    assert exc.value.code == "hedra_timeout" and not exc.value.final


def test_parse_job_variants():
    assert (
        parse_job({"id": "a", "status": "SUCCEEDED", "asset": {"asset": {"url": "u"}}}).output_url
        == "u"
    )
    assert parse_job({"id": "a", "state": "failed", "error": "x"}).status == "error"
    assert parse_job({}).status == "queued"
    assert parse_job({"id": "a", "status": "complete", "cost": "abc"}).cost is None


async def test_estimate_is_best_effort():
    assert (
        await _client(lambda r: httpx.Response(500)).estimate(resolution="720p", duration_ms=1000)
        is None
    )
    assert await _client(lambda r: httpx.Response(200, json={"cost": 0.5})).estimate(
        resolution="720p", duration_ms=1000
    ) == {"cost": 0.5}

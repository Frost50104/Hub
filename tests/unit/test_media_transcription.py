"""Сторож галлюцинаций, сшивка кусков, зазоры и сериализация транскрипта."""

from __future__ import annotations

import json
import struct
import wave
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.services.media.transcription import base, get_provider
from app.services.media.transcription.base import Segment, Word
from app.services.media.transcription.local_unit import LocalUnitProvider, TranscriptionError
from app.services.media.transcription.openai_compat import (
    OpenAICompatProvider,
    parse_verbose_json,
)


def seg(s, e, t, **kw):
    return Segment(start=s, end=e, text=t, **kw)


def test_hallucination_guard():
    assert base.hallucination_guard(seg(0, 1, "Привет"))
    assert not base.hallucination_guard(seg(0, 1, "   "))
    assert not base.hallucination_guard(seg(0, 1, "..."))
    assert not base.hallucination_guard(seg(0, 1, "Субтитры сделал DimaTorzok"))
    assert not base.hallucination_guard(seg(0, 1, "Продолжение следует..."))
    assert not base.hallucination_guard(seg(0, 1, "да да да да", compression_ratio=3.0))
    assert not base.hallucination_guard(seg(0, 1, "шум", no_speech_prob=0.9, avg_logprob=-1.5))
    # Одного признака мало (как в Listen: оба порога разом).
    assert base.hallucination_guard(seg(0, 1, "тихо", no_speech_prob=0.9, avg_logprob=-0.5))
    assert base.hallucination_guard(seg(0, 1, "тихо", no_speech_prob=0.3, avg_logprob=-1.5))


def test_stitch_joins_across_chunk_boundary_without_sentence_end():
    chunks = [
        (0.0, [seg(0, 2, "Сегодня мы")]),
        (2.0, [seg(0.1, 1.5, "поговорим о Hub."), seg(2.0, 3.0, "Начнём.")]),
    ]
    out = base.stitch(chunks)
    assert [s.text for s in out] == ["Сегодня мы поговорим о Hub.", "Начнём."]
    assert (out[0].start, out[0].end) == (0.0, 3.5)
    assert (out[1].start, out[1].end) == (4.0, 5.0)


def test_stitch_respects_sentence_end_and_gap():
    chunks = [(0.0, [seg(0, 2, "Готово.")]), (2.0, [seg(0.1, 1, "Дальше")])]
    assert [s.text for s in base.stitch(chunks)] == ["Готово.", "Дальше"]
    chunks = [(0.0, [seg(0, 2, "Без точки")]), (2.0, [seg(0.5, 1, "далеко")])]
    assert [s.text for s in base.stitch(chunks)] == ["Без точки", "далеко"]
    assert base.stitch([]) == []


def test_offset_words_json_and_plain_text():
    s = seg(0, 1, "a", words=[Word(0.0, 0.5, "a")])
    out = base.offset_segments([s], 10)
    assert out[0].words[0].start == 10.0
    assert base.segments_to_json(out) == [
        {"s": 10.0, "e": 11.0, "t": "a", "w": [[10.0, 10.5, "a"]]}
    ]
    assert base.segments_to_json([seg(0, 1, " b ")]) == [{"s": 0.0, "e": 1.0, "t": "b"}]
    assert base.plain_text([seg(0, 1, " a "), seg(1, 2, ""), seg(2, 3, "b")]) == "a b"


def test_transcript_gaps():
    gaps = base.transcript_gaps([{"s": 1, "e": 2}, {"s": 2.5, "e": 4}], 5)
    assert gaps == [(0.0, 1.0), (2.0, 2.5), (4.0, 5.0)]
    assert base.transcript_gaps([], 3) == [(0.0, 3.0)]
    assert base.transcript_gaps([seg(0, 3, "x")], 3) == []


# ─── Провайдеры: локальный юнит кусками и OpenAI-совместимый ──────────────────
def _wav(path: Path, seconds: float, rate: int = 16000) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack("<" + "h" * int(seconds * rate), *([0] * int(seconds * rate))))


async def test_local_unit_provider_chunks_stitches_and_retries(tmp_path):
    wav = tmp_path / "a.wav"
    _wav(wav, 120.0)
    calls: list[httpx.Request] = []
    sleeps: list[float] = []

    async def fake_sleep(sec: float) -> None:
        sleeps.append(sec)

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(503, json={"detail": "грузится"})
        n = len(calls) - 1  # 1..3
        body = {
            "segments": [
                {
                    "s": 1.0,
                    "e": 2.0,
                    "t": f"кусок {n}",
                    "avg_logprob": -0.2,
                    "no_speech_prob": 0.1,
                    "compression_ratio": 1.0,
                    "w": [[1.0, 1.5, "кусок"], [1.5, 2.0, str(n)]],
                },
                {
                    "s": 40.0,
                    "e": 41.0,
                    "t": "Субтитры сделал DimaTorzok",
                    "avg_logprob": -1.2,
                    "no_speech_prob": 0.9,
                },
            ],
            "duration_sec": 50.0,
        }
        return httpx.Response(200, json=body)

    provider = LocalUnitProvider(
        base_url="http://stt.local/",
        model="faster-whisper/small",
        chunk_sec=55,
        pause_sec=1.0,
        transport=httpx.MockTransport(handler),
        sleep=fake_sleep,
    )
    progress: list[tuple[int, int]] = []

    async def on_chunk(done: int, total: int) -> None:
        progress.append((done, total))

    result = await provider.transcribe_file(
        wav,
        language="ru",
        glossary="Signaris, Hub",
        beam_size=1,
        duration=120.0,
        silences=[(50.0, 51.0), (100.0, 101.0)],
        on_chunk=on_chunk,
    )
    assert len(calls) == 4  # 503 + три куска
    req = calls[1]
    assert req.url.path == "/transcribe-segments"
    assert req.url.params["language"] == "ru" and req.url.params["beam_size"] == "1"
    assert req.url.params["initial_prompt"] == "Signaris, Hub"
    assert req.url.params["word_timestamps"] == "true"
    assert req.headers["content-type"] == "audio/wav"
    assert req.content[:4] == b"RIFF"
    assert progress == [(1, 3), (2, 3), (3, 3)]
    # Сторож выкинул галлюцинацию; смещения кусков — 0 / 50,5 / 100 (второй
    # рез жёсткий: тишина на 100,5 оставила бы хвост короче min_len).
    assert [s.text for s in result.segments] == ["кусок 1", "кусок 2", "кусок 3"]
    assert [round(s.start, 1) for s in result.segments] == [1.0, 51.5, 101.0]
    assert result.segments[1].words[0].start == pytest.approx(51.5)
    assert (result.provider, result.model, result.duration_sec) == (
        "local",
        "faster-whisper/small",
        120.0,
    )
    # Ожидание 503 (5 с) + две паузы между кусками.
    assert sleeps == [5.0, 1.0, 1.0]


@pytest.mark.parametrize(
    ("status", "code", "final"),
    [(413, "chunk_too_long", True), (404, "stt_no_segments_route", True), (400, "stt_error", True)],
)
async def test_local_unit_provider_final_errors(tmp_path, status, code, final):
    wav = tmp_path / "a.wav"
    _wav(wav, 5.0)
    provider = LocalUnitProvider(
        base_url="http://stt.local",
        model="m",
        transport=httpx.MockTransport(lambda r: httpx.Response(status, text="nope")),
    )
    with pytest.raises(TranscriptionError) as exc:
        await provider.transcribe_file(
            wav, language="ru", glossary="", beam_size=1, duration=5.0, silences=[]
        )
    assert exc.value.code == code and exc.value.final is final


async def test_local_unit_provider_gives_up_after_retries(tmp_path):
    wav = tmp_path / "a.wav"
    _wav(wav, 5.0)
    sleeps: list[float] = []

    async def fake_sleep(sec: float) -> None:
        sleeps.append(sec)

    provider = LocalUnitProvider(
        base_url="http://stt.local",
        model="m",
        transport=httpx.MockTransport(lambda r: httpx.Response(503)),
        sleep=fake_sleep,
    )
    with pytest.raises(TranscriptionError) as exc:
        await provider.transcribe_file(
            wav, language="ru", glossary="", beam_size=1, duration=5.0, silences=[]
        )
    assert exc.value.code == "stt_busy" and exc.value.final is False
    assert sleeps == [5.0, 15.0, 30.0, 60.0, 120.0]

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    sleeps.clear()
    provider = LocalUnitProvider(
        base_url="http://stt.local",
        model="m",
        transport=httpx.MockTransport(boom),
        sleep=fake_sleep,
    )
    with pytest.raises(TranscriptionError) as exc:
        await provider.transcribe_file(
            wav, language="ru", glossary="", beam_size=1, duration=5.0, silences=[]
        )
    assert exc.value.code == "stt_unreachable" and sleeps == [3.0, 10.0, 30.0]


async def test_local_unit_provider_respects_cancel(tmp_path):
    import asyncio

    wav = tmp_path / "a.wav"
    _wav(wav, 5.0)
    cancel = asyncio.Event()
    cancel.set()
    provider = LocalUnitProvider(
        base_url="http://stt.local",
        model="m",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"segments": []})),
    )
    with pytest.raises(TranscriptionError) as exc:
        await provider.transcribe_file(
            wav, language="ru", glossary="", beam_size=1, duration=5.0, silences=[], cancel=cancel
        )
    assert exc.value.code == "cancelled"


def test_parse_verbose_json_distributes_words_and_falls_back_to_text():
    data = {
        "text": "раз два три",
        "segments": [
            {
                "start": 0.0,
                "end": 1.0,
                "text": " раз ",
                "avg_logprob": -0.1,
                "no_speech_prob": 0.0,
                "compression_ratio": 1.0,
            },
            {"start": 1.0, "end": 2.5, "text": "два три"},
        ],
        "words": [
            {"word": "раз", "start": 0.1, "end": 0.6},
            {"word": "два", "start": 1.1, "end": 1.5},
            {"word": "три", "start": 1.6, "end": 2.4},
        ],
    }
    segs = parse_verbose_json(data)
    assert [s.text for s in segs] == ["раз", "два три"]
    assert [w.text for w in segs[1].words] == ["два", "три"]
    assert segs[0].avg_logprob == -0.1 and segs[1].avg_logprob is None
    only_text = parse_verbose_json({"text": "всё", "duration": 3.0})
    assert len(only_text) == 1 and only_text[0].end == 3.0 and only_text[0].text == "всё"
    assert parse_verbose_json({}) == []


async def test_openai_compat_provider_posts_multipart_and_maps_auth_error(tmp_path):
    wav = tmp_path / "a.wav"
    _wav(wav, 5.0)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.headers["authorization"] != "Bearer k":
            return httpx.Response(401, text="bad key")
        return httpx.Response(200, json={"segments": [{"start": 0.5, "end": 1.0, "text": "ок"}]})

    provider = OpenAICompatProvider(
        api_key="k",
        base_url="https://api.x/v1/",
        model="whisper-1",
        transport=httpx.MockTransport(handler),
    )
    result = await provider.transcribe_file(
        wav, language="ru", glossary="Hub", beam_size=1, duration=5.0, silences=[]
    )
    assert result.provider == "openai" and [s.text for s in result.segments] == ["ок"]
    req = seen[0]
    assert req.url == "https://api.x/v1/audio/transcriptions"
    body = req.content.decode("utf-8", "replace")
    for field in ("whisper-1", "verbose_json", 'name="prompt"', "Hub", 'filename="chunk.wav"'):
        assert field in body
    bad = OpenAICompatProvider(
        api_key="wrong",
        base_url="https://api.x/v1",
        model="whisper-1",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(TranscriptionError) as exc:
        await bad.transcribe_file(
            wav, language="ru", glossary="", beam_size=1, duration=5.0, silences=[]
        )
    assert exc.value.code == "stt_auth" and exc.value.final


def test_get_provider_selection():
    def settings(**kw):
        base = {
            "media_stt_provider": "local",
            "media_stt_url": None,
            "media_stt_api_key": None,
            "media_stt_base_url": None,
            "media_stt_model": "whisper-1",
            "stt_model": "small",
            "media_stt_chunk_sec": 55.0,
            "media_stt_pause_sec": 1.0,
        }
        base.update(kw)
        return SimpleNamespace(**base)

    assert get_provider(settings()) is None
    assert get_provider(settings(media_stt_provider="openai")) is None
    local = get_provider(settings(media_stt_url="http://127.0.0.1:5071"))
    assert isinstance(local, LocalUnitProvider)
    assert (local.base_url, local.model, local.chunk_sec) == (
        "http://127.0.0.1:5071",
        "faster-whisper/small",
        55.0,
    )
    remote = get_provider(
        settings(
            media_stt_provider="openai",
            media_stt_api_key="k",
            media_stt_base_url="https://api.x/v1",
        )
    )
    assert isinstance(remote, OpenAICompatProvider) and remote.model == "whisper-1"
    assert json.dumps({"ok": True})  # json используется выше в теле multipart-проверок

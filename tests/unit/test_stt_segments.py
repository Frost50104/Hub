"""`/transcribe-segments` STT-юнита (0066): параметры декодера, форма
сегментов, общий замок/лимит с голосовой командой, коды ответов."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.config import get_settings


@pytest.fixture(autouse=True)
def _clear_settings():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def stt_local(monkeypatch):
    from app.services.stt import local

    monkeypatch.setattr(local, "_model", object())
    monkeypatch.setattr(local, "_state", "ready")
    monkeypatch.setattr(local, "_busy_since", None)
    monkeypatch.setattr(local, "_lock", asyncio.Lock())
    return local


class FakeModel:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def transcribe(self, samples, **kw):
        self.calls.append(kw)
        word = SimpleNamespace(start=0.1, end=0.5, word=" Привет")
        seg = SimpleNamespace(
            start=0.0,
            end=1.5,
            text=" Привет, Hub. ",
            avg_logprob=-0.3,
            no_speech_prob=0.02,
            compression_ratio=1.1,
            words=[word],
        )
        return iter([seg]), SimpleNamespace(language="ru")


def test_run_segments_passes_decoder_params_and_shapes_output(stt_local):
    model = FakeModel()
    out = stt_local._run_segments(
        model,
        [0.0],
        language="ru",
        beam_size=2,
        initial_prompt="Signaris, Hub",
        word_timestamps=True,
    )
    assert out == [
        {
            "s": 0.0,
            "e": 1.5,
            "t": "Привет, Hub.",
            "avg_logprob": -0.3,
            "no_speech_prob": 0.02,
            "compression_ratio": 1.1,
            "w": [[0.1, 0.5, "Привет"]],
        }
    ]
    kw = model.calls[0]
    assert kw["word_timestamps"] is True
    assert kw["initial_prompt"] == "Signaris, Hub"
    assert kw["condition_on_previous_text"] is False
    assert kw["beam_size"] == 2 and kw["vad_filter"] is True
    # Без слов — ключа `w` нет; пустой prompt → None.
    out = stt_local._run_segments(
        model, [0.0], language="ru", beam_size=1, initial_prompt="", word_timestamps=False
    )
    assert "w" not in out[0]
    assert model.calls[1]["initial_prompt"] is None


async def test_transcribe_segments_shares_lock_limit_and_busy(stt_local, monkeypatch):
    from app.services.stt import STTTooLong

    monkeypatch.setenv("SIGNARIS_HUB_STT_MAX_AUDIO_SEC", "60")
    get_settings.cache_clear()
    monkeypatch.setattr(stt_local, "_decode", lambda _audio: [0.0] * (10 * stt_local.SAMPLE_RATE))
    seen = {}

    def fake_run(_model, _samples, **kw):
        seen["busy"] = stt_local.busy_seconds()
        seen["kw"] = kw
        return [{"s": 0.0, "e": 1.0, "t": "ок"}]

    monkeypatch.setattr(stt_local, "_run_segments", fake_run)
    result = await stt_local.LocalWhisper().transcribe_segments(
        b"x", language="ru", beam_size=9, initial_prompt="Hub"
    )
    assert result.segments == [{"s": 0.0, "e": 1.0, "t": "ок"}]
    assert result.duration_sec == 10.0
    assert seen["busy"] is not None and stt_local.busy_seconds() is None
    assert seen["kw"]["beam_size"] == 5  # потолок

    monkeypatch.setattr(stt_local, "_decode", lambda _audio: [0.0] * (61 * stt_local.SAMPLE_RATE))
    with pytest.raises(STTTooLong) as err:
        await stt_local.LocalWhisper().transcribe_segments(b"x", language="ru")
    assert "Кусок длиннее 60 с" in str(err.value)


async def test_voice_command_path_is_unchanged(stt_local, monkeypatch):
    """Рефакторинг общего пути не меняет голосовую команду: текст и
    длительность те же, занятость снимается."""
    monkeypatch.setattr(stt_local, "_decode", lambda _audio: [0.0] * stt_local.SAMPLE_RATE)
    monkeypatch.setattr(stt_local, "_run", lambda _m, _s, _lang: "поставь задачу")
    result = await stt_local.LocalWhisper().transcribe(b"x", content_type="audio/webm")
    assert (result.text, result.duration_sec) == ("поставь задачу", 1.0)
    assert stt_local.busy_seconds() is None


def _request(body: bytes):
    async def read() -> bytes:
        return body

    async def gone() -> bool:
        return False

    return SimpleNamespace(body=read, is_disconnected=gone, headers={})


async def test_endpoint_maps_errors_and_requires_local_provider(monkeypatch):
    import app.stt_service as svc
    from app.services.stt import STTTooLong, local

    with pytest.raises(HTTPException) as exc:
        await svc.transcribe_segments(_request(b""))
    assert exc.value.status_code == 422

    class Remote:
        name = "openai"

    monkeypatch.setattr(svc, "get_stt", lambda: Remote())
    with pytest.raises(HTTPException) as exc:
        await svc.transcribe_segments(_request(b"x"))
    assert exc.value.status_code == 501

    class Fake(local.LocalWhisper):
        seen: dict = {}

        async def transcribe_segments(self, audio, **kw):
            Fake.seen = kw
            if kw["beam_size"] == 3:
                raise STTTooLong("Кусок длиннее 60 с")
            return local.SegmentsResult(segments=[{"s": 0, "e": 1, "t": "ок"}], duration_sec=1.0)

    monkeypatch.setattr(svc, "get_stt", lambda: Fake())
    out = await svc.transcribe_segments(
        _request(b"x"), language="ru", beam_size=1, initial_prompt="x" * 600
    )
    assert out == {"segments": [{"s": 0, "e": 1, "t": "ок"}], "duration_sec": 1.0}
    assert len(Fake.seen["initial_prompt"]) == 500
    with pytest.raises(HTTPException) as exc:
        await svc.transcribe_segments(_request(b"x"), beam_size=3)
    assert exc.value.status_code == 413

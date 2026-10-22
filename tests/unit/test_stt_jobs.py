"""Задания вокруг распознавания речи: проверка после деплоя и скачивание модели."""

from __future__ import annotations

import os
import sys
import time

import httpx
import pytest

from app.jobs import stt_fetch_model, stt_smoke


class _Health:
    def __init__(self, statuses: list[str]) -> None:
        self.statuses = statuses
        self.calls = 0

    def get(self, _url: str) -> httpx.Response:
        self.calls += 1
        status = self.statuses.pop(0)
        if status == "down":
            raise httpx.ConnectError("refused")
        return httpx.Response(200 if status == "ready" else 503, json={"status": status})


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(stt_smoke.time, "sleep", lambda _s: None)


def test_smoke_waits_for_the_model_after_restart():
    client = _Health(["down", "loading", "ready"])
    status = stt_smoke.wait_ready(client, "http://stt", deadline=time.monotonic() + 60)
    assert status == "ready"
    assert client.calls == 3


@pytest.mark.parametrize("final", ["missing", "error", "disabled"])
def test_smoke_does_not_wait_for_a_final_failure(final):
    client = _Health([final])
    assert stt_smoke.wait_ready(client, "http://stt", deadline=time.monotonic() + 60) == final
    assert client.calls == 1


def test_smoke_gives_up_at_the_deadline():
    client = _Health(["loading"])
    assert stt_smoke.wait_ready(client, "http://stt", deadline=time.monotonic() - 1) == "loading"


def test_unit_memory_reads_cgroup_files(tmp_path):
    unit = tmp_path / "signaris-hub-stt.service"
    unit.mkdir()
    (unit / "memory.current").write_text("1048576\n")
    (unit / "memory.peak").write_text("2097152\n")
    assert stt_smoke.unit_memory_mb("signaris-hub-stt.service", tmp_path) == {
        "current_mb": 1,
        "peak_mb": 2,
    }
    assert stt_smoke.unit_memory_mb("missing.service", tmp_path) == {}


def test_smoke_sample_ships_with_the_code():
    """Образец лежит в ops/, а ops/ уезжает на сервер rsync'ом (docs/ и web/ — нет)."""
    assert stt_smoke.SAMPLE.is_file()
    assert stt_smoke.SAMPLE.stat().st_size > 1200


def test_fetch_refuses_without_the_shared_cache_dir(monkeypatch):
    """Без SIGNARIS_HUB_STT_CACHE_DIR веса легли бы в ~/.cache, а юнит,
    читающий только свой кэш, так и отвечал бы «не настроено»."""
    monkeypatch.delenv("SIGNARIS_HUB_STT_CACHE_DIR", raising=False)
    # monkeypatch запоминает исходные значения — задание меняет их само.
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("HF_HUB_DISABLE_XET", "0")
    monkeypatch.setattr("app.log.configure", lambda: None)

    assert stt_fetch_model.main() == 2
    assert "faster_whisper" not in sys.modules
    # Задание обязано идти в сеть, даже запущенное с окружением юнита, и без xet.
    assert os.environ["HF_HUB_OFFLINE"] == "0"
    assert os.environ["HF_HUB_DISABLE_XET"] == "1"

"""Сторож systemd для юнита распознавания речи (`app/services/stt/watchdog.py`).

До 21.10 сторожа не было, и юнит шесть недель простоял за `memory.high`, не
отвечая даже на `/health`. Пинг из цикла событий доказывает, что процесс жив;
пинг, сорвавшийся из-за исключения, убил бы здоровый процесс через минуту.
"""

from __future__ import annotations

import asyncio
import os
import socket
import sys
import tempfile
from pathlib import Path

import pytest
from structlog.testing import capture_logs

from app.services.stt import watchdog


def test_interval_is_a_third_of_the_watchdog_timeout():
    assert watchdog.interval_sec({"WATCHDOG_USEC": "60000000"}) == 20.0


@pytest.mark.parametrize(
    "env", [{}, {"WATCHDOG_USEC": ""}, {"WATCHDOG_USEC": "abc"}, {"WATCHDOG_USEC": "0"}]
)
def test_no_watchdog_means_no_pings(env):
    """Без переменных systemd (локальный запуск, юнит без WatchdogSec) пинговать
    некому — до установки нового юнита новый код живёт и со старым."""
    assert watchdog.interval_sec(env) is None


def test_inherited_watchdog_of_another_process_is_ignored():
    env = {"WATCHDOG_USEC": "60000000", "WATCHDOG_PID": str(os.getpid() + 1)}
    assert watchdog.interval_sec(env) is None
    env["WATCHDOG_PID"] = str(os.getpid())
    assert watchdog.interval_sec(env) == 20.0


def test_should_ping_until_busy_for_too_long():
    assert watchdog.should_ping(None, 180)
    assert watchdog.should_ping(25.0, 180)
    assert not watchdog.should_ping(181.0, 180)


def test_notify_without_socket_is_a_no_op():
    assert watchdog.notify(b"WATCHDOG=1", {}) is False


def test_notify_reaches_a_real_datagram_socket():
    # Короткий путь в /tmp: на macOS путь unix-сокета ограничен 104 символами,
    # а tmp_path pytest туда не влезает.
    with tempfile.TemporaryDirectory(dir="/tmp") as tmp:
        path = str(Path(tmp) / "n.sock")
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as server:
            server.bind(path)
            assert watchdog.notify(b"WATCHDOG=1", {"NOTIFY_SOCKET": path}) is True
            assert server.recv(64) == b"WATCHDOG=1"


@pytest.mark.skipif(sys.platform != "linux", reason="абстрактные unix-сокеты есть только в Linux")
def test_notify_supports_abstract_socket_address():
    name = f"hub-stt-test-{os.getpid()}"
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as server:
        server.bind("\0" + name)
        assert watchdog.notify(b"WATCHDOG=1", {"NOTIFY_SOCKET": "@" + name}) is True
        assert server.recv(64) == b"WATCHDOG=1"


def test_notify_to_a_dead_socket_does_not_raise():
    assert watchdog.notify(b"WATCHDOG=1", {"NOTIFY_SOCKET": "/tmp/hub-no-such-socket"}) is False


async def _run_for(seconds: float, **kwargs) -> None:
    task = asyncio.create_task(watchdog.run(**kwargs))
    await asyncio.sleep(seconds)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_pings_survive_an_exception_in_a_tick():
    calls = {"n": 0}

    def busy() -> float | None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("сбой витка")
        return None

    sent: list[bytes] = []
    with capture_logs() as logs:
        await _run_for(0.2, busy=busy, max_busy_sec=180, interval=0.01, send=sent.append)
    assert sent and set(sent) == {b"WATCHDOG=1"}
    assert any(e["event"] == "stt.watchdog_error" for e in logs)


async def test_stuck_work_stops_pings_and_is_logged_once():
    sent: list[bytes] = []
    with capture_logs() as logs:
        await _run_for(0.2, busy=lambda: 999.0, max_busy_sec=180, interval=0.01, send=sent.append)
    assert sent == []
    assert [e["event"] for e in logs].count("stt.stuck") == 1

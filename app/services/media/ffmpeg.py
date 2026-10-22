"""Единственное место, где конвейер зовёт бинари `ffmpeg`/`ffprobe`.

Остальные модули строят аргументы чистыми функциями; здесь — запуск под
таймаутом, разбор `-progress pipe:1`, хвост stderr для диагностики, отмена
через `asyncio.Event` (heartbeat увидел `cancel_requested`). Разбор прогресса
вынесен в чистые функции — CI без бинаря.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger("media.ffmpeg")

GLOBAL_FLAGS = ["-nostdin", "-hide_banner", "-y"]
STDERR_TAIL_BYTES = 4096
# Анализирующие команды (`silencedetect`, `astats`, `loudnorm`) пишут результат
# в stderr на уровне info — для них хвоста мало, нужен весь вывод (с потолком).
STDERR_FULL_MAX = 2 * 1024 * 1024


class FfmpegError(RuntimeError):
    def __init__(self, message: str, *, code: int | None = None, stderr_tail: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.stderr_tail = stderr_tail


def parse_progress_line(line: str) -> tuple[str, str] | None:
    """Строка `key=value` из `-progress pipe:1`; мусор → None."""
    line = line.strip()
    if not line or "=" not in line:
        return None
    key, _, value = line.partition("=")
    return key.strip(), value.strip()


@dataclass
class Progress:
    out_time_sec: float = 0.0
    speed: float | None = None
    frames: int | None = None
    done: bool = False
    raw: dict[str, str] = field(default_factory=dict)

    def feed(self, line: str) -> bool:
        """→ True, когда пришёл блок `progress=` (момент обновить heartbeat)."""
        kv = parse_progress_line(line)
        if kv is None:
            return False
        key, value = kv
        self.raw[key] = value
        # `out_time_ms` у ffmpeg тоже в микросекундах (историческая опечатка);
        # берём его, только пока не пришёл `out_time_us`.
        is_us = key == "out_time_us" or (key == "out_time_ms" and "out_time_us" not in self.raw)
        if is_us and value.lstrip("-").isdigit():
            self.out_time_sec = max(0.0, int(value) / 1_000_000)
        elif key == "speed":
            try:
                self.speed = float(value.rstrip("x"))
            except ValueError:
                self.speed = None
        elif key == "frame" and value.isdigit():
            self.frames = int(value)
        elif key == "progress":
            self.done = value == "end"
            return True
        return False

    def pct(self, duration: float | None) -> int | None:
        if not duration or duration <= 0:
            return None
        return int(max(0, min(100, round(self.out_time_sec / duration * 100))))


def timeout_for(duration: float | None, *, factor: float, floor: float = 600.0) -> float:
    """Потолок времени ffmpeg: кратно длительности, но не меньше `floor`."""
    return max(floor, float(duration or 0.0) * factor)


async def run(
    args: list[str],
    *,
    bin_path: str,
    timeout_sec: float,
    on_progress: Callable[[Progress], Awaitable[None]] | None = None,
    cancel: asyncio.Event | None = None,
    capture_stderr: bool = False,
    loglevel: str = "error",
    nice: int | None = 10,
) -> str:
    """Запустить ffmpeg. → stderr (хвост, либо весь при `capture_stderr`).

    `on_progress` зовётся на каждом блоке `progress=` (раз в ~0,5 с у ffmpeg) —
    туда воркер вешает heartbeat. `cancel` — убить процесс (отмена задания или
    SIGTERM воркера). Таймаут — kill + FfmpegError('timeout').
    """
    cmd = [bin_path, *GLOBAL_FLAGS, "-loglevel", loglevel, "-progress", "pipe:1", *args]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert proc.stdout is not None and proc.stderr is not None
    _renice(proc.pid, nice)
    progress = Progress()
    tail: deque[bytes] = deque(maxlen=64)
    full: list[bytes] = []
    full_size = 0

    async def pump_stdout() -> None:
        async for raw in proc.stdout:
            if progress.feed(raw.decode("utf-8", "replace")) and on_progress is not None:
                await on_progress(progress)

    async def pump_stderr() -> None:
        nonlocal full_size
        async for raw in proc.stderr:
            tail.append(raw[-STDERR_TAIL_BYTES:])
            if capture_stderr and full_size < STDERR_FULL_MAX:
                full.append(raw)
                full_size += len(raw)

    async def watch_cancel() -> None:
        if cancel is None:
            await asyncio.Event().wait()
        else:
            await cancel.wait()
            proc.kill()

    pumps = asyncio.gather(pump_stdout(), pump_stderr())
    canceller = asyncio.create_task(watch_cancel())
    try:
        try:
            await asyncio.wait_for(pumps, timeout=timeout_sec)
            code = await asyncio.wait_for(proc.wait(), timeout=30)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            raise FfmpegError(
                f"ffmpeg: превышен потолок {timeout_sec:.0f} с",
                code=None,
                stderr_tail=_text(tail),
            ) from None
    finally:
        canceller.cancel()
        pumps.cancel()
    if cancel is not None and cancel.is_set():
        raise FfmpegError("ffmpeg: отменено", code=code, stderr_tail=_text(tail))
    if code != 0:
        text = _text(tail)
        log.warning("media.ffmpeg_failed", code=code, tail=text[-600:])
        raise FfmpegError(f"ffmpeg завершился с кодом {code}", code=code, stderr_tail=text)
    return b"".join(full).decode("utf-8", "replace") if capture_stderr else _text(tail)


def _text(tail: deque[bytes]) -> str:
    return b"".join(tail).decode("utf-8", "replace")[-STDERR_TAIL_BYTES:]


def _renice(pid: int, nice: int | None) -> None:
    """Понизить приоритет дочернего ffmpeg (абсолютное значение nice). Юнит и
    так идёт под `Nice=10`; здесь — страховка для запуска вне systemd
    (`media_measure.py`, разработка). Ошибка не критична."""
    if nice is None or not hasattr(os, "setpriority"):
        return
    try:
        os.setpriority(os.PRIO_PROCESS, pid, nice)
    except (OSError, ProcessLookupError):
        pass


async def probe_json(path: Path, *, bin_path: str, timeout_sec: float = 60.0) -> dict[str, Any]:
    """`ffprobe` → словарь JSON (разбор — `probe.parse_ffprobe`)."""
    cmd = [
        bin_path,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout_sec)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise FfmpegError("ffprobe: превышен потолок времени") from None
    if proc.returncode != 0:
        tail = err.decode("utf-8", "replace")[-STDERR_TAIL_BYTES:]
        raise FfmpegError(
            f"ffprobe завершился с кодом {proc.returncode}",
            code=proc.returncode,
            stderr_tail=tail,
        )
    try:
        return json.loads(out.decode("utf-8", "replace") or "{}")
    except json.JSONDecodeError as exc:
        raise FfmpegError(f"ffprobe: не JSON ({exc})") from None

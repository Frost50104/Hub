"""Пинги сторожа systemd для юнита signaris-hub-stt (`WatchdogSec`).

Пинг уходит из ЦИКЛА СОБЫТИЙ, поэтому доказывает, что процесс жив: встал цикл
— пингов нет, через `WatchdogSec` systemd шлёт SIGABRT (faulthandler из
`PYTHONFAULTHANDLER=1` пишет в журнал стеки всех потоков), а `Restart=always`
поднимает юнит заново. Работа под замком, которая идёт дольше
`stt_max_busy_sec`, тоже останавливает пинги: цикл жив, а расшифровка встала.

До 21.10 сторожа не было, и юнит шесть недель простоял, не отвечая даже на
`/health` (docs/tech-debt/incidents.md).

Зависимостей нет нарочно: протокол sd_notify — одна датаграмма в unix-сокет.
"""

from __future__ import annotations

import asyncio
import os
import socket
from collections.abc import Callable, Mapping

import structlog

log = structlog.get_logger("stt.watchdog")


def interval_sec(env: Mapping[str, str] | None = None) -> float | None:
    """Пауза между пингами — треть таймаута; None, если сторож не включён.

    `WATCHDOG_PID` чужого процесса значит, что переменные унаследованы, а
    пинговать должен другой: systemd с `NotifyAccess=main` пинг не примет.
    """
    env = os.environ if env is None else env
    raw = env.get("WATCHDOG_USEC")
    if not raw:
        return None
    pid = env.get("WATCHDOG_PID")
    if pid and pid != str(os.getpid()):
        return None
    try:
        usec = int(raw)
    except ValueError:
        return None
    return usec / 1_000_000 / 3 if usec > 0 else None


def should_ping(busy_sec: float | None, max_busy_sec: float) -> bool:
    """Свободен или занят не дольше порога — живой."""
    return busy_sec is None or busy_sec <= max_busy_sec


def notify(message: bytes, env: Mapping[str, str] | None = None) -> bool:
    """Одна датаграмма в `$NOTIFY_SOCKET`. Исключений наружу нет: упавшая
    задача пингов значит убитый через минуту здоровый процесс."""
    env = os.environ if env is None else env
    addr = env.get("NOTIFY_SOCKET")
    if not addr:
        return False
    if addr.startswith("@"):
        addr = "\0" + addr[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.connect(addr)
            sock.sendall(message)
    except OSError:
        return False
    return True


async def run(
    busy: Callable[[], float | None],
    max_busy_sec: float,
    *,
    interval: float,
    send: Callable[[bytes], bool] = notify,
) -> None:
    """Пингует, пока процесс не занят дольше порога. Не падает ни от чего,
    кроме отмены: исключение витка пишется в журнал, следующий виток — заново."""
    stuck_logged = False
    while True:
        await asyncio.sleep(interval)
        try:
            busy_sec = busy()
            if should_ping(busy_sec, max_busy_sec):
                send(b"WATCHDOG=1")
                stuck_logged = False
            elif not stuck_logged:
                log.error("stt.stuck", busy_sec=round(busy_sec or 0.0), max_busy_sec=max_busy_sec)
                stuck_logged = True
        except Exception as e:  # noqa: BLE001
            log.warning("stt.watchdog_error", error=f"{type(e).__name__}: {e}")

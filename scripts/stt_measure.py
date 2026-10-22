"""Замер памяти и времени распознавания речи — калибровка юнита signaris-hub-stt.

Лимиты юнита (`MemoryMax`, `stt_max_audio_sec`, `stt_max_busy_sec`) считаются
от замера на ЭТОЙ машине и с ЭТИМИ версиями пакетов из `[stt]`. Подняли
версии — повторить замер и пересчитать лимиты (docs/DEPLOY.md §«Распознавание
речи»). До 21.10 лимиты стояли по августовскому замеру RSS, и юнит шесть недель
простоял между `memory.high` и `memory.max` (docs/tech-debt/incidents.md).

Запуск на VPS — во ВРЕМЕННОМ юните с окружением боевого, но с запасом памяти и
без MemoryHigh: иначе замер сам попадёт в ловушку, которую калибрует.

    systemd-run --wait --pipe --uid=signaris -p MemoryMax=2G -p CPUWeight=30 \\
      -p EnvironmentFile=/opt/signaris-hub/.env \\
      -p Environment=HF_HOME=/opt/signaris-hub/stt-cache \\
      -p Environment=HF_HUB_OFFLINE=1 -p Environment=OMP_NUM_THREADS=2 \\
      -p WorkingDirectory=/opt/signaris-hub \\
      /opt/signaris-hub/.venv/bin/python /opt/signaris-hub/scripts/stt_measure.py \\
      /tmp/stt-cmd.webm /tmp/stt-cmd.m4a /tmp/stt-120s.webm /tmp/stt-2mb.webm

`--download-only` меряет скачивание модели (нужны чистый `HF_HOME` и
`HF_HUB_OFFLINE=0`) — сколько памяти уходит на hf_xet внутри процесса.

Печатает по строке JSON на фазу. Текст расшифровки не печатается — только его
длина: на живых записях там рабочие команды сотрудников.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import math
import threading
import time
from pathlib import Path

MB = 1024 * 1024
SAMPLE_RATE = 16000
# Запас над пиком anon под страничный кэш весов и код библиотек: у
# `memory.max` ядро вытесняет их первыми, но без запаса процесс пробуксовывает.
CACHE_HEADROOM_MB = 300


def _cgroup_dir() -> Path | None:
    try:
        line = Path("/proc/self/cgroup").read_text().splitlines()[0]
    except (OSError, IndexError):
        return None
    path = Path("/sys/fs/cgroup") / line.split("::", 1)[-1].lstrip("/")
    return path if path.is_dir() else None


def _anon_bytes(cg: Path | None) -> int:
    if cg is None:
        return 0
    try:
        for row in (cg / "memory.stat").read_text().splitlines():
            if row.startswith("anon "):
                return int(row.split()[1])
    except (OSError, ValueError):
        pass
    return 0


def _read_int(path: Path) -> int | None:
    try:
        return int(path.read_text().split()[0])
    except (OSError, ValueError, IndexError):
        return None


def _status_mb(field: str) -> int | None:
    try:
        for row in Path("/proc/self/status").read_text().splitlines():
            if row.startswith(field + ":"):
                return round(int(row.split()[1]) / 1024)
    except (OSError, ValueError):
        pass
    return None


class AnonSampler(threading.Thread):
    """Пик anon своей cgroup по фазам: `memory.peak` включает кэш, а VmHWM —
    отображённые файлы, поэтому anon сэмплируется отдельно (раз в 50 мс)."""

    def __init__(self, cg: Path | None) -> None:
        super().__init__(daemon=True)
        self.cg = cg
        self.peak = 0
        self.overall = 0

    def reset(self) -> None:
        self.peak = _anon_bytes(self.cg)

    def run(self) -> None:
        while True:
            now = _anon_bytes(self.cg)
            self.peak = max(self.peak, now)
            self.overall = max(self.overall, now)
            time.sleep(0.05)


class Meter:
    def __init__(self) -> None:
        self.cg = _cgroup_dir()
        self.sampler = AnonSampler(self.cg)
        self.sampler.start()
        self.lag = 0.0
        self.max_lag = 0.0
        self.max_busy = 0.0

    async def lag_monitor(self) -> None:
        """Задержка цикла событий: пинг сторожа идёт из цикла, и если потоки
        расшифровки его душат, порог сторожа обязан это покрывать."""
        tick = 0.1
        while True:
            started = time.monotonic()
            await asyncio.sleep(tick)
            self.lag = max(self.lag, time.monotonic() - started - tick)

    def start(self) -> float:
        self.sampler.reset()
        self.lag = 0.0
        return time.monotonic()

    def emit(self, phase: str, started: float, **extra: object) -> None:
        seconds = time.monotonic() - started
        self.max_lag = max(self.max_lag, self.lag)
        self.max_busy = max(self.max_busy, seconds)
        peak = _read_int(self.cg / "memory.peak") if self.cg else None
        row = {
            "phase": phase,
            "seconds": round(seconds, 1),
            "anon_peak_mb": round(self.sampler.peak / MB),
            "anon_now_mb": round(_anon_bytes(self.cg) / MB),
            "vm_hwm_mb": _status_mb("VmHWM"),
            "vm_rss_mb": _status_mb("VmRSS"),
            "cgroup_peak_mb": round(peak / MB) if peak is not None else None,
            "loop_lag_max_sec": round(self.lag, 2),
            **extra,
        }
        print(json.dumps(row, ensure_ascii=False), flush=True)


async def measure(paths: list[str], transcribe_up_to_sec: float) -> None:
    from app.config import get_settings

    settings = get_settings()
    meter = Meter()
    monitor = asyncio.create_task(meter.lag_monitor())

    started = meter.start()
    import faster_whisper

    meter.emit("import", started)

    started = meter.start()
    model = await asyncio.to_thread(
        faster_whisper.WhisperModel,
        settings.stt_model,
        device="cpu",
        compute_type=settings.stt_compute_type,
        cpu_threads=settings.stt_cpu_threads,
    )
    meter.emit("load", started, model=settings.stt_model)

    for raw in paths:
        path = Path(raw)
        data = path.read_bytes()
        started = meter.start()
        audio = await asyncio.to_thread(
            faster_whisper.decode_audio, io.BytesIO(data), sampling_rate=SAMPLE_RATE
        )
        audio_sec = len(audio) / SAMPLE_RATE
        meter.emit(
            "decode", started, file=path.name, bytes=len(data), audio_sec=round(audio_sec, 1)
        )
        if audio_sec > transcribe_up_to_sec:
            # Только декодирование: такую запись сервис отклонит по длине, а
            # память декодирования (до проверки длины) уже записана выше.
            del audio
            continue

        def run(audio=audio) -> str:
            segments, _info = model.transcribe(
                audio, language=settings.stt_language, beam_size=1, vad_filter=True
            )
            return " ".join(s.text.strip() for s in segments).strip()

        started = meter.start()
        text = await asyncio.to_thread(run)
        seconds = time.monotonic() - started
        meter.emit(
            "transcribe",
            started,
            file=path.name,
            audio_sec=round(audio_sec, 1),
            rtf=round(seconds / max(audio_sec, 0.1), 2),
            text_chars=len(text),
        )
        del audio, run

    monitor.cancel()
    worst_mb = meter.sampler.overall / MB
    print(
        json.dumps(
            {
                "phase": "summary",
                "anon_peak_overall_mb": round(worst_mb),
                "vm_hwm_mb": _status_mb("VmHWM"),
                "loop_lag_max_sec": round(meter.max_lag, 2),
                "longest_phase_sec": round(meter.max_busy, 1),
                "recommended_memory_max_mb": int(
                    math.ceil((worst_mb + CACHE_HEADROOM_MB) / 50) * 50
                ),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


async def download_only() -> None:
    from app.config import get_settings

    settings = get_settings()
    meter = Meter()
    started = meter.start()
    from faster_whisper import download_model

    path = await asyncio.to_thread(download_model, settings.stt_model)
    meter.emit("download", started, files=sorted(p.name for p in Path(path).iterdir()))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("samples", nargs="*", help="записи для расшифровки (webm/m4a/wav)")
    parser.add_argument(
        "--transcribe-up-to-sec",
        type=float,
        default=150.0,
        help="записи длиннее только декодируются: сервис отклонит их по длине",
    )
    parser.add_argument("--download-only", action="store_true")
    args = parser.parse_args()
    if args.download_only:
        asyncio.run(download_only())
    else:
        if not args.samples:
            parser.error("нужен хотя бы один образец записи")
        asyncio.run(measure(args.samples, args.transcribe_up_to_sec))


if __name__ == "__main__":
    main()

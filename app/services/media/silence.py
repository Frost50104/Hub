"""Разбор текстового вывода ffmpeg-фильтров (`silencedetect`, `astats`,
`loudnorm`) и порог тишины относительно шумового пола. Чистые функции."""

from __future__ import annotations

import json
import re

from app.services.media.edl import Interval

_SIL_START = re.compile(r"silence_start:\s*(-?\d+(?:\.\d+)?)")
_SIL_END = re.compile(r"silence_end:\s*(-?\d+(?:\.\d+)?)")
_NOISE_FLOOR = re.compile(r"Noise floor dB:\s*(-?\d+(?:\.\d+)?|-inf|inf)")
_LOUDNORM_JSON = re.compile(r"\{[^{}]*\"input_i\"[^{}]*\}", re.S)


def parse_silencedetect(stderr: str, *, duration: float | None = None) -> list[Interval]:
    """Пары `silence_start`/`silence_end`. Незакрытая тишина (до конца файла)
    закрывается `duration`, если он известен, иначе отбрасывается."""
    out: list[Interval] = []
    start: float | None = None
    for line in stderr.splitlines():
        m = _SIL_START.search(line)
        if m:
            start = float(m.group(1))
            continue
        m = _SIL_END.search(line)
        if m and start is not None:
            end = float(m.group(1))
            if end > start:
                out.append((max(0.0, start), end))
            start = None
    if start is not None and duration is not None and duration > start:
        out.append((max(0.0, start), float(duration)))
    return out


def parse_noise_floor(stderr: str) -> float | None:
    """`astats … measure_overall=Noise_floor` → последнее значение (Overall)."""
    values = [m.group(1) for m in _NOISE_FLOOR.finditer(stderr)]
    if not values:
        return None
    last = values[-1]
    if last in ("-inf", "inf"):
        return None
    return float(last)


def threshold_db(noise_floor: float | None, *, offset: float = 12.0) -> float:
    """Порог `silencedetect`: на `offset` дБ выше шумового пола, в разумных
    рамках. Без замера — консервативные −40 дБ."""
    if noise_floor is None:
        return -40.0
    return max(-60.0, min(-35.0, noise_floor + offset))


def parse_loudnorm_json(stderr: str) -> dict[str, float]:
    """Блок JSON, который `loudnorm=print_format=json` печатает в конце
    первого прохода. → измеренные значения числами."""
    m = _LOUDNORM_JSON.search(stderr)
    if not m:
        raise ValueError("loudnorm: JSON измерений не найден в выводе ffmpeg")
    raw = json.loads(m.group(0))
    out: dict[str, float] = {}
    for key in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset"):
        if key in raw:
            try:
                out[key] = float(raw[key])
            except (TypeError, ValueError):
                continue
    missing = {"input_i", "input_tp", "input_lra", "input_thresh"} - set(out)
    if missing:
        raise ValueError(f"loudnorm: нет полей {sorted(missing)}")
    return out

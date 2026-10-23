"""Уровень звука по кадрам (RMS каждые ~100 мс: `astats` + `ametadata`) и
решения по нему: уровень речи, порог «громко», доля громкого времени в зазоре,
тихие отрезки без транскрипта. Чистые функции — под юнит-тестами.

Почему не `silencedetect` от шумового пола: OBS режет тишину в цифровой ноль,
`astats` даёт «Noise floor» −144 дБ или −inf, порог падал на запасные −40 дБ,
а дыхание и щелчки клавиатуры рвали «тишину» на куски короче минимума — пауза
0:14–0:20 на записи Дианы 23.10 не считалась паузой вовсе. Теперь порог
считается ОТ РЕЧИ (медиана RMS внутри слов минус `offset`), а пауза — зазор
между словами, где громкого времени не больше `max_loud_fraction`: короткий
«пфр» или щелчок уходит вместе с паузой, а речь, которую Whisper пропустил,
остаётся — в ней громко почти всё время. Замер 23.10 на 90 минутах: из 335
зазоров ≥ 1,5 с ни у одного доля громкого не превысила 50 % при пороге
«речь − 15 дБ».
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from statistics import median

from app.services.media.edl import EPS, Interval, normalize

Frame = tuple[float, float]  # (время начала кадра, RMS дБ)

SILENT_DB = -120.0
DEFAULT_THRESHOLD_DB = -40.0
_PTS = re.compile(r"pts_time:\s*(-?\d+(?:\.\d+)?)")
_RMS = re.compile(r"lavfi\.astats\.Overall\.RMS_level=(-?\d+(?:\.\d+)?|-inf|inf|nan)")


def parse_levels(text: str) -> list[Frame]:
    """Вывод `ametadata=mode=print:key=lavfi.astats.Overall.RMS_level`:
    строка `frame:N pts:… pts_time:T` и следом `lavfi.astats.Overall.RMS_level=V`.
    `-inf`/`nan` (цифровая тишина) → `SILENT_DB`."""
    out: list[Frame] = []
    t: float | None = None
    for line in text.splitlines():
        m = _PTS.search(line)
        if m:
            t = float(m.group(1))
            continue
        m = _RMS.search(line)
        if m and t is not None:
            raw = m.group(1)
            if raw in ("-inf", "nan"):
                value = SILENT_DB
            elif raw == "inf":
                value = 0.0
            else:
                value = max(SILENT_DB, float(raw))
            out.append((t, value))
            t = None
    return out


def frame_step(frames: Sequence[Frame]) -> float:
    """Шаг кадров (медиана разностей); без данных — 0,1 с."""
    if len(frames) < 2:
        return 0.1
    diffs = [b[0] - a[0] for a, b in zip(frames, frames[1:], strict=False) if b[0] > a[0]]
    return median(diffs) if diffs else 0.1


def values_in(frames: Sequence[Frame], intervals: Iterable[Interval]) -> list[float]:
    """RMS кадров, чьё начало попадает в интервалы (нормализованные)."""
    out: list[float] = []
    spans = normalize(intervals)
    i = 0
    for s, e in spans:
        while i < len(frames) and frames[i][0] < s:
            i += 1
        j = i
        while j < len(frames) and frames[j][0] < e:
            out.append(frames[j][1])
            j += 1
        i = j
    return out


def speech_level_db(frames: Sequence[Frame], speech: Iterable[Interval]) -> float | None:
    """Медиана RMS внутри слов транскрипта. Нет слов/кадров — None."""
    values = values_in(frames, speech)
    return median(values) if values else None


def fallback_speech_level_db(frames: Sequence[Frame]) -> float | None:
    """Без транскрипта: 75-й перцентиль не-тихих кадров — речь громче пауз,
    и верхняя четверть почти наверняка речь."""
    values = sorted(v for _, v in frames if v > SILENT_DB + 1.0)
    if not values:
        return None
    return values[min(len(values) - 1, (3 * len(values)) // 4)]


def threshold_db(
    speech_level: float | None, *, offset: float = 15.0, lo: float = -55.0, hi: float = -30.0
) -> float:
    """Порог «громко»: на `offset` дБ тише речи, в разумных рамках; без
    замера — запасные −40 дБ."""
    if speech_level is None:
        return DEFAULT_THRESHOLD_DB
    return max(lo, min(hi, speech_level - offset))


def loud_fraction(frames: Sequence[Frame], interval: Interval, thr: float) -> float:
    """Доля кадров интервала громче порога (нет кадров — 0: считаем тишиной)."""
    values = values_in(frames, [interval])
    if not values:
        return 0.0
    return sum(1 for v in values if v > thr) / len(values)


def pauses_from_gaps(
    gaps: Iterable[Interval],
    frames: Sequence[Frame],
    thr: float,
    *,
    min_pause: float,
    max_loud_fraction: float = 0.5,
) -> list[Interval]:
    """Паузы = зазоры между словами длиннее порога, где громкого времени не
    больше `max_loud_fraction`. Зазор с речью, которую Whisper пропустил,
    громок почти целиком и остаётся нетронутым."""
    out: list[Interval] = []
    for s, e in normalize(gaps):
        if e - s < min_pause - EPS:
            continue
        if loud_fraction(frames, (s, e), thr) <= max_loud_fraction + EPS:
            out.append((s, e))
    return out


def silent_runs(frames: Sequence[Frame], thr: float, *, min_len: float) -> list[Interval]:
    """Без транскрипта: отрезки подряд идущих кадров не громче порога, длиннее
    `min_len`. Конец отрезка — начало следующего громкого кадра."""
    if not frames:
        return []
    step = frame_step(frames)
    out: list[Interval] = []
    start: float | None = None
    for t, v in frames:
        if v <= thr:
            if start is None:
                start = t
            continue
        if start is not None:
            if t - start >= min_len - EPS:
                out.append((start, t))
            start = None
    if start is not None:
        end = frames[-1][0] + step
        if end - start >= min_len - EPS:
            out.append((start, end))
    return out

"""Учёт просмотра видео (Ф3a): merge интервалов + покрытие.

Клиент шлёт просмотренные интервалы [[start, end], …] пингами (~15 сек)
и sendBeacon'ом на pagehide; сервер мёржит их в block_state под FOR UPDATE
(два устройства параллельно — adversarial-ревью §29). «Досмотрено» =
покрытие ≥ WATCH_THRESHOLD длительности — UI-контроль обходим, серверная
проверка интервалов остаётся единственной гарантией (deterrence-модель).

Длительность (знаменатель покрытия) с 0043 знает сервер: `media_files.
duration_sec`, прочитанная из mp4 при загрузке. Клиентское число — только
фолбэк для файлов, у которых moov не разобрался, и оно НЕ уточняется
пингами: см. `resolve_duration`.
"""

from __future__ import annotations

import math

import structlog

log = structlog.get_logger("video_progress")

WATCH_THRESHOLD = 0.9
# Щель короче — считаем одним куском. Полсекунды не хватало: после перемотки
# первый шаг всегда теряется (клиент не засчитывает шаг с флагом `seeking`), и
# в записи оставались микро-дыры по 1–2 с — на проде у одного ролика их две,
# 1.9 с и 1.0 с. Человек их не пропускал, а процент недобирал. Константа
# обязана совпадать с `GAP_CLOSE` в `web/src/lib/videoWatch.ts`: разойдутся —
# разойдутся и проценты на экране с гейтом.
GAP_CLOSE_SEC = 2.0
# Сколько интервалов храним. Схема приёма (`VideoProgressBody`) обязана быть
# НЕ МЕНЬШЕ: приём 200 против хранения 500 означал, что на 201-м сохранённом
# интервале прогресс переставал сохраняться навсегда (422 на каждый пинг).
MAX_INTERVALS = 500
# Куски короче — артефакты скраббинга, а не просмотр; ими и жертвуем при
# переполнении.
MIN_INTERVAL_SEC = 0.25
# Коридор доверия к клиентской длительности (шум реальных данных ~1e-4 с).
# Шире нельзя: гейт — watched/D ≥ 0.9, значит завышение знаменателя всего в
# 1/0.9 = 1,112 раза уже делает завершение невозможным.
DURATION_TOLERANCE = 0.02
MAX_DURATION_SEC = 24 * 3600

# Дедуп предупреждений: пинги идут раз в 15 с, без него один битый плеер
# зальёт лог. Ключ — (profile_id, media_id); множество ограничено, чтобы не
# протекать в долгоживущем процессе.
_warned: set[tuple[str, str]] = set()
_WARN_LIMIT = 2048


def normalize_duration(value: object) -> float | None:
    """Пригодная длительность в секундах или None.

    None — это «не знаем», а не ошибка запроса: клиент присылает `null`
    вместо Infinity (JSON.stringify так делает), и отвечать на это 422 значило
    бы терять интервалы у всех, у кого не читается длительность.
    """
    try:
        seconds = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not math.isfinite(seconds) or seconds <= 0 or seconds > MAX_DURATION_SEC:
        return None
    return seconds


def resolve_duration(
    *,
    server: object = None,
    stored: object = None,
    incoming: object = None,
    profile_id: str | None = None,
    media_id: str | None = None,
) -> float | None:
    """Какое число считать длительностью ролика.

    Порядок: серверное (прочитано из файла) → уже сохранённое → присланное.

    Сохранённое НЕ переписывается пингами. Файл под media_id неизменяем, так
    что уточнять нечего, а любое «принимаем в пределах ±2%» позволяет клиенту
    уползти на 2% за пинг и за десяток пингов загнать себя в вечный 409.
    Расхождение больше коридора — повод для лога, но не для 4xx: клиент,
    получивший ошибку, перестанет слать и интервалы тоже.
    """
    known = normalize_duration(server)
    if known is not None:
        return known
    saved = normalize_duration(stored)
    fresh = normalize_duration(incoming)
    if saved is None:
        return fresh
    if fresh is not None and abs(fresh - saved) > DURATION_TOLERANCE * saved:
        _warn_once(profile_id, media_id, saved=saved, incoming=fresh)
    return saved


def _warn_once(
    profile_id: str | None, media_id: str | None, *, saved: float, incoming: float
) -> None:
    key = (profile_id or "?", media_id or "?")
    if key in _warned:
        return
    if len(_warned) >= _WARN_LIMIT:
        _warned.clear()
    _warned.add(key)
    log.warning(
        "video.duration_mismatch",
        profile_id=key[0],
        media_id=key[1],
        stored=round(saved, 3),
        incoming=round(incoming, 3),
    )


def merge_intervals(
    existing: list[list[float]], incoming: list[list[float]]
) -> list[list[float]]:
    """Слить интервалы, нормализовав мусор (start>end, отрицательные)."""
    cleaned: list[list[float]] = []
    for pair in [*existing, *incoming][: MAX_INTERVALS * 2]:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            continue
        try:
            start, end = float(pair[0]), float(pair[1])
        except (TypeError, ValueError):
            continue
        if not (math.isfinite(start) and math.isfinite(end)):
            continue
        if start < 0 or end <= start:
            continue
        cleaned.append([start, end])
    cleaned.sort()
    merged: list[list[float]] = []
    for start, end in cleaned:
        if merged and start <= merged[-1][1] + GAP_CLOSE_SEC:  # смыкаем щели
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return _truncate(merged)


def _truncate(merged: list[list[float]]) -> list[list[float]]:
    """Ужать список до MAX_INTERVALS, жертвуя САМЫМИ КОРОТКИМИ кусками.

    Прежний `merged[:MAX]` резал хвост — то есть конец ролика, ровно те
    проценты, которых требует гейт: два устройства с разными перемотками
    надёжно отрезали друг другу концовку.
    """
    if len(merged) <= MAX_INTERVALS:
        return merged
    keep = sorted(
        sorted(
            range(len(merged)),
            # Длинные важнее коротких; при равной длине важнее ПОЗДНИЕ — конец
            # ролика решает гейт, а начало человек и так уже прошёл.
            key=lambda i: (merged[i][1] - merged[i][0], i),
            reverse=True,
        )[:MAX_INTERVALS]
    )
    return [merged[i] for i in keep]


def coverage(intervals: list[list[float]], duration: float | None) -> float:
    """Доля просмотренного [0..1]. Неизвестная длительность → 0."""
    if not duration or duration <= 0:
        return 0.0
    watched = sum(end - start for start, end in intervals)
    return min(1.0, watched / duration)


def is_watched(intervals: list[list[float]], duration: float | None) -> bool:
    return coverage(intervals, duration) >= WATCH_THRESHOLD

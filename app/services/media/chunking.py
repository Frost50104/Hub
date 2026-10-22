"""Нарезка звука на куски: для STT-юнита (≤ 55 с, по тишине) и для Hedra
(≤ 600 с, по зазорам транскрипта). WAV режется stdlib `wave` — без второго
вызова ffmpeg и под юнит-тестом."""

from __future__ import annotations

import io
import wave
from collections.abc import Iterable, Iterator
from pathlib import Path

from app.services.media.edl import EPS, Interval, normalize


def plan_chunks(
    duration: float,
    silences: Iterable[Interval],
    *,
    target: float = 50.0,
    max_len: float = 55.0,
    min_len: float = 20.0,
) -> list[Interval]:
    """Куски для STT: рез в середине ближайшей к `t+target` тишины внутри окна
    `[t+min_len, t+max_len]`, иначе жёстко на `t+max_len`. Хвост короче
    `min_len` не оставляем: если он получится, рез сдвигается левее."""
    duration = float(duration)
    if duration <= EPS:
        return []
    mids = sorted((s + e) / 2.0 for s, e in normalize(silences))
    out: list[Interval] = []
    t = 0.0
    while duration - t > max_len + EPS:
        lo, hi = t + min_len, min(t + max_len, duration - min_len)
        candidates = [m for m in mids if lo <= m <= hi]
        if candidates:
            cut = min(candidates, key=lambda m: abs(m - (t + target)))
        else:
            cut = hi if hi > lo else t + max_len
        out.append((t, cut))
        t = cut
    out.append((t, duration))
    return out


def plan_hedra_chunks(
    segments: Iterable[Interval],
    gaps: Iterable[Interval],
    *,
    max_len: float = 600.0,
    min_len: float = 0.5,
) -> list[Interval]:
    """Куски для Hedra: каждый отрезок гуся длиннее `max_len` режется по самому
    длинному зазору транскрипта во второй половине допустимого окна; остатки
    короче `min_len` приклеиваются к предыдущему куску."""
    gap_list = normalize(gaps)
    out: list[Interval] = []
    for s, e in normalize(segments):
        cur = s
        while e - cur > max_len + EPS:
            lo, hi = cur + max_len / 2.0, cur + max_len
            inside = [(gs, ge) for gs, ge in gap_list if gs >= lo and ge <= hi and ge - gs > EPS]
            if inside:
                gs, ge = max(inside, key=lambda g: g[1] - g[0])
                cut = (gs + ge) / 2.0
            else:
                cut = hi
            out.append((cur, cut))
            cur = cut
        if e - cur >= min_len - EPS or not out:
            out.append((cur, e))
        else:
            ps, _ = out[-1]
            out[-1] = (ps, e)
    return out


def read_wav_slices(path: Path, ranges: Iterable[Interval]) -> Iterator[bytes]:
    """Куски WAV как самостоятельные WAV-файлы в памяти (заголовок + кадры)."""
    with wave.open(str(path), "rb") as src:
        rate = src.getframerate()
        params = src.getparams()
        total_frames = src.getnframes()
        for s, e in ranges:
            start = max(0, min(total_frames, int(round(s * rate))))
            end = max(start, min(total_frames, int(round(e * rate))))
            src.setpos(start)
            frames = src.readframes(end - start)
            buf = io.BytesIO()
            with wave.open(buf, "wb") as dst:
                dst.setparams(params)
                dst.writeframes(frames)
            yield buf.getvalue()

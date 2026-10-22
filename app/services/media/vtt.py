"""WebVTT из сегментов транскрипта. Правила cue — под читаемость в плеере
(и под `<track>` на телефоне): не длиннее 7 с, не больше двух строк по 42
знака, не короче 1 с, без пересечений."""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any

MAX_CUE_SEC = 7.0
MAX_LINE_CHARS = 42
MAX_LINES = 2
MIN_CUE_SEC = 1.0


def fmt_ts(sec: float) -> str:
    sec = max(0.0, float(sec))
    ms = int(round(sec * 1000))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def wrap_lines(text: str, *, max_chars: int = MAX_LINE_CHARS, max_lines: int = MAX_LINES) -> str:
    """Перенос по словам в ≤ `max_lines` строк по ≤ `max_chars`; лишнее не
    режется, а остаётся в последней строке (лучше длинная строка, чем потеря слов)."""
    words = text.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        if not cur:
            cur = w
        elif len(cur) + 1 + len(w) <= max_chars or len(lines) == max_lines - 1:
            cur = f"{cur} {w}"
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return "\n".join(lines)


def _split_segment(seg: dict[str, Any]) -> list[tuple[float, float, str]]:
    """Один сегмент → один или несколько cue по лимитам длины и времени."""
    s, e, text = float(seg["s"]), float(seg["e"]), str(seg.get("t") or "").strip()
    if not text:
        return []
    limit_chars = MAX_LINE_CHARS * MAX_LINES
    if e - s <= MAX_CUE_SEC and len(text) <= limit_chars:
        return [(s, e, text)]
    words = seg.get("w") or []
    if words:
        pieces: list[tuple[float, float, str]] = []
        cur_words: list[list[Any]] = []
        for w in words:
            ws, we, wt = float(w[0]), float(w[1]), str(w[2]).strip()
            cur_text = " ".join(x[2] for x in cur_words)
            too_long = cur_words and (
                len(cur_text) + 1 + len(wt) > limit_chars
                or we - float(cur_words[0][0]) > MAX_CUE_SEC
            )
            if too_long:
                pieces.append((float(cur_words[0][0]), float(cur_words[-1][1]), cur_text))
                cur_words = []
            cur_words.append([ws, we, wt])
        if cur_words:
            pieces.append(
                (float(cur_words[0][0]), float(cur_words[-1][1]), " ".join(x[2] for x in cur_words))
            )
        return pieces
    # Без слов — делим текст на равные доли по времени.
    n = max(1, math.ceil(len(text) / limit_chars), math.ceil((e - s) / MAX_CUE_SEC))
    ws = text.split()
    per = math.ceil(len(ws) / n)
    pieces = []
    step = (e - s) / n
    for i in range(n):
        chunk = " ".join(ws[i * per : (i + 1) * per])
        if chunk:
            pieces.append((s + i * step, s + (i + 1) * step, chunk))
    return pieces


def build_vtt(segments: Iterable[dict[str, Any]]) -> str:
    cues: list[tuple[float, float, str]] = []
    for seg in segments:
        cues.extend(_split_segment(seg))
    cues.sort(key=lambda c: c[0])
    fixed: list[tuple[float, float, str]] = []
    for i, (s, e, text) in enumerate(cues):
        if fixed and s < fixed[-1][1]:
            s = fixed[-1][1]
        if e - s < MIN_CUE_SEC:
            # Дотянуть до минимума, но не наехать на следующий cue; если
            # следующий ближе минимума — оставить как есть.
            nxt = cues[i + 1][0] if i + 1 < len(cues) else float("inf")
            e = max(e, min(s + MIN_CUE_SEC, nxt))
        if e - s <= 0:
            continue
        fixed.append((s, e, text))
    lines = ["WEBVTT", ""]
    for s, e, text in fixed:
        lines.append(f"{fmt_ts(s)} --> {fmt_ts(e)}")
        lines.append(wrap_lines(text))
        lines.append("")
    return "\n".join(lines)

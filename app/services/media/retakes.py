"""Перезаписи (брак дублей) по транскрипту: голосовые метки автора («Стоп»,
«Заново», «Ещё раз», «Это вырезаем») и повтор начала фразы после паузы.
Чистая математика над словами транскрипта — под юнит-тестами, без БД.

Кандидат — отрезок `[start, end)` ИСХОДНОЙ записи, который предлагается
вырезать целиком (паузы, в отличие от него, ужимаются). По решению владельца
23.10 уверенные кандидаты («high»: голосовая метка или совпадение ≥ 2 слов)
режутся автоматически, неуверенные («low») показываются автору выключенными.

Замер на полной записи Дианы (90 мин): 23 голосовые метки («Стоп», «Заново»,
«Это вырезаем», «Ещё раз пишу», «Так, стоп. Зановал.»), 27 повторов начала
фразы после паузы ≥ 2 с («Выбираем проект.» → «Выбираем проект. У нас…»).
Чего эвристика НЕ видит: Whisper выбрасывает повторённое слово как дубль
(«Важно, [6 с] весь офис» вместо «Важно, … Важно, весь офис») — такую дыру
закрывает правило пауз по словам (`levels.pauses_from_gaps`), а не этот модуль.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Literal

from app.services.media.edl import EPS

Reason = Literal["marker", "repeat"]
Confidence = Literal["high", "low"]

# Начало следующего слова по Whisper обычно на 50–100 мс позже реального
# вдоха-атаки — режем чуть раньше, чтобы не отрезать первый звук хорошего дубля.
LEAD_SEC = 0.08
# Зазор, с которого ищем повтор начала фразы без голосовой метки.
REPEAT_MIN_GAP_SEC = 1.2
# Новая реплика — после такой паузы или после точки/вопроса/восклицания.
UTTERANCE_GAP_SEC = 0.6
# Две метки подряд («Так, стоп.» «Заново.») — одна метка.
MARKER_JOIN_GAP_SEC = 2.0
# Вырезка «только метка» захватывает не больше такого хвоста тишины после неё.
MARKER_TAIL_SEC = 1.5
MAX_SPAN_SEC = 60.0
LOOKBACK_TOKENS = 15
REPEAT_LOOKBACK_TOKENS = 12
LOW_REPEAT_MAX_RUN = 8
# Совпали два слова — уверенно только если и дальше фразы похожи.
SIMILAR_RUN_RATIO = 0.55
# Реплика с меткой внутри содержательной фразы («Выходим в стопе», «Так,
# проехали, стоп, понеслась звезда по кочкам») — неуверенный кандидат.
MIXED_MARKER_MAX_WORDS = 12
LOW_MARKER_WORDS = frozenset({"проехали", "проехала", "переснимаю", "перепишем"})

MARKER_CORE = frozenset(
    {
        "стоп",
        "заново",
        "вырезаем",
        "вырезать",
        "вырежем",
        "вырезай",
        "вырежи",
        "перепишу",
        "перезапишу",
        "перезаписываю",
        "переснимем",
        "переснимаем",
        "сначала",
    }
)
# «Ещё раз» — метка только парой («раз» и «ещё» порознь — обычные слова).
MARKER_BIGRAMS = frozenset({("еще", "раз"), ("давай", "заново"), ("давайте", "заново")})
FILLERS = frozenset(
    {
        "так",
        "ну",
        "все",
        "это",
        "пишу",
        "говорю",
        "давай",
        "давайте",
        "ок",
        "окей",
        "а",
        "и",
        "щас",
        "сейчас",
        "секунду",
        "секундочку",
        "минуту",
        "минутку",
        "ага",
        "да",
        "нет",
        "короче",
        "блин",
        "упс",
        "ой",
        "вот",
        "всё",
        "еще",
        "раз",
        "кусок",
        "целый",
        "момент",
        "здесь",
        "тут",
        "его",
        "её",
    }
)
_SENTENCE_END = (".", "!", "?", "…")
_WORD_CHARS = re.compile(r"[^\wё]+", re.U)

Token = tuple[float, float, str]  # (start, end, текст как в транскрипте)


@dataclass(frozen=True)
class Retake:
    start: float
    end: float
    reason: Reason
    confidence: Confidence
    marker: str | None
    before: str
    after: str

    def to_json(self) -> dict[str, Any]:
        return {
            "s": round(self.start, 2),
            "e": round(self.end, 2),
            "reason": self.reason,
            "confidence": self.confidence,
            "marker": self.marker,
            "before": self.before,
            "after": self.after,
        }


def norm(text: str) -> str:
    """Нижний регистр, `ё → е`, без пунктуации."""
    return _WORD_CHARS.sub("", text.lower().replace("ё", "е"))


def tokens_of(segments: list[dict[str, Any]]) -> list[Token]:
    """Слова транскрипта. У реплики без пословных таймкодов (старый транскрипт,
    удалённый провайдер) слова раскладываются по её длительности равномерно."""
    out: list[Token] = []
    for seg in segments:
        words = seg.get("w") or []
        if words:
            out.extend((float(w[0]), float(w[1]), str(w[2])) for w in words)
            continue
        parts = str(seg.get("t") or "").split()
        if not parts:
            continue
        s, e = float(seg["s"]), float(seg["e"])
        step = max(0.0, e - s) / len(parts)
        for n, part in enumerate(parts):
            out.append((round(s + n * step, 3), round(s + (n + 1) * step, 3), part))
    out.sort(key=lambda t: (t[0], t[1]))
    return out


def _is_marker_core(word: str) -> bool:
    if word in MARKER_CORE:
        return True
    # Whisper: «Зановал», «вырезаем»/«вырезаю» и т. п.
    return word.startswith("занов") or word.startswith("вырез") or word.startswith("перезап")


def is_marker_utterance(words: list[str]) -> bool:
    """Реплика — голосовая метка: коротка, содержит ядро метки и ничего, кроме
    меток и слов-связок. «Стоп. На платформе проехали.» — НЕ метка (есть
    содержательные слова), «Так, стоп.» и «Ещё раз пишу.» — метки."""
    if not words or len(words) > 6:
        return False
    has_core = any(_is_marker_core(w) for w in words) or any(
        (a, b) in MARKER_BIGRAMS for a, b in zip(words, words[1:], strict=False)
    )
    if not has_core:
        return False
    return all(_is_marker_core(w) or w in FILLERS for w in words)


def utterances(tokens: list[Token]) -> list[tuple[int, int]]:
    """Индексы `[i, j)` реплик: граница — пауза ≥ `UTTERANCE_GAP_SEC` или
    конец предложения у предыдущего слова."""
    out: list[tuple[int, int]] = []
    start = 0
    for i in range(1, len(tokens) + 1):
        if i == len(tokens):
            out.append((start, i))
            break
        prev = tokens[i - 1]
        gap = tokens[i][0] - prev[1]
        if gap >= UTTERANCE_GAP_SEC - EPS or prev[2].rstrip("»\"'").endswith(_SENTENCE_END):
            out.append((start, i))
            start = i
    return out


def _match(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if len(a) >= 5 and len(b) >= 5:
        return SequenceMatcher(None, a, b).ratio() >= 0.8
    return a == b


def best_match(before: list[str], after: list[str]) -> tuple[int, int]:
    """Самое длинное совпадение начала `after` (до 3 слов) с окном в `before`,
    ближайшее к концу `before` → `(k, j)`; нет — `(0, -1)`."""
    for k in (3, 2, 1):
        if len(after) < k or len(before) < k:
            continue
        for j in range(len(before) - k, -1, -1):
            if all(_match(before[j + i], after[i]) for i in range(k)):
                return k, j
    return 0, -1


def run_similarity(tokens: list[Token], start: int, restart: int) -> float:
    """Похожесть брака `[start, restart)` на такое же число слов после
    перезапуска — отличает «мы можем … / мы можем …» (переформулировка той
    же мысли) от двух разных фраз с одинаковым началом."""
    n = restart - start
    before = " ".join(norm(t[2]) for t in tokens[start:restart])
    after = " ".join(norm(t[2]) for t in tokens[restart : restart + n])
    if not before or not after:
        return 0.0
    return SequenceMatcher(None, before, after).ratio()


def _text(tokens: list[Token], i: int, j: int, *, limit: int | None = None) -> str:
    items = tokens[i:j]
    if limit is not None:
        items = items[:limit]
    return " ".join(t[2] for t in items).strip()


def _span_start(tokens: list[Token], index: int) -> float:
    """Начало вырезки у слова `index`: чуть раньше слова, но не раньше конца
    предыдущего."""
    s = tokens[index][0] - LEAD_SEC
    if index > 0:
        s = max(s, tokens[index - 1][1])
    return max(0.0, s)


def find_retakes(
    segments: list[dict[str, Any]],
    *,
    duration: float,
    max_span: float = MAX_SPAN_SEC,
) -> list[Retake]:
    tokens = tokens_of(segments)
    if not tokens:
        return []
    utts = utterances(tokens)
    marker_utt = [is_marker_utterance([norm(t[2]) for t in tokens[i:j]]) for i, j in utts]
    in_marker = [False] * len(tokens)
    for (i, j), flag in zip(utts, marker_utt, strict=True):
        if flag:
            for k in range(i, j):
                in_marker[k] = True

    # Метки подряд — одна серия.
    runs: list[tuple[int, int]] = []
    for (i, j), flag in zip(utts, marker_utt, strict=True):
        if not flag:
            continue
        if runs and tokens[i][0] - tokens[runs[-1][1] - 1][1] < MARKER_JOIN_GAP_SEC:
            runs[-1] = (runs[-1][0], j)
        else:
            runs.append((i, j))

    out: list[Retake] = []
    for i, j in runs:
        after = [norm(t[2]) for t in tokens[j : j + 3]]
        lo = max(0, i - LOOKBACK_TOKENS)
        # Окно «до» не заходит за предыдущую метку.
        for k in range(i - 1, lo - 1, -1):
            if in_marker[k]:
                lo = k + 1
                break
        before = [norm(t[2]) for t in tokens[lo:i]]
        k, rel = best_match(before, after)
        if j < len(tokens):
            end = tokens[j][0] - LEAD_SEC
            restart_at = tokens[j][0]
        else:
            end = min(duration, tokens[j - 1][1])
            restart_at = end
        start_index = i
        if k >= 2 or (k == 1 and len(after[0]) >= 4):
            cand = lo + rel
            if restart_at - tokens[cand][0] <= max_span:
                start_index = cand
        if start_index == i:
            # Только метка: хвост тишины до перезапуска — дело правила пауз,
            # вырезка не должна выглядеть минутной из-за молчания после «Стоп».
            end = min(end, tokens[j - 1][1] + MARKER_TAIL_SEC)
        start = _span_start(tokens, start_index)
        end = max(start + EPS, min(end, duration))
        out.append(
            Retake(
                start=start,
                end=end,
                reason="marker",
                confidence="high",
                marker=_text(tokens, i, j),
                before=_text(tokens, start_index, j),
                after=_text(tokens, j, len(tokens), limit=6),
            )
        )

    # Метка внутри содержательной реплики — вырезать саму реплику, неуверенно.
    for (i, j), flag in zip(utts, marker_utt, strict=True):
        if flag or j - i > MIXED_MARKER_MAX_WORDS:
            continue
        words = [norm(t[2]) for t in tokens[i:j]]
        has_core = any(_is_marker_core(w) or w in LOW_MARKER_WORDS for w in words) or any(
            (a, b) in MARKER_BIGRAMS for a, b in zip(words, words[1:], strict=False)
        )
        if not has_core:
            continue
        start = _span_start(tokens, i)
        end = tokens[j][0] - LEAD_SEC if j < len(tokens) else min(duration, tokens[j - 1][1])
        end = min(end, tokens[j - 1][1] + MARKER_TAIL_SEC)
        out.append(
            Retake(
                start=start,
                end=max(start + EPS, min(end, duration)),
                reason="marker",
                confidence="low",
                marker=_text(tokens, i, j),
                before=_text(tokens, i, j),
                after=_text(tokens, j, len(tokens), limit=6),
            )
        )

    # Повтор начала фразы после паузы без метки.
    for i in range(1, len(tokens)):
        gap = tokens[i][0] - tokens[i - 1][1]
        if gap < REPEAT_MIN_GAP_SEC - EPS or in_marker[i] or in_marker[i - 1]:
            continue
        lo = max(0, i - REPEAT_LOOKBACK_TOKENS)
        for k in range(i - 1, lo - 1, -1):
            if in_marker[k]:
                lo = k + 1
                break
        before = [norm(t[2]) for t in tokens[lo:i]]
        after = [norm(t[2]) for t in tokens[i : i + 3]]
        k, rel = best_match(before, after)
        if k == 0:
            continue
        cand = lo + rel
        if tokens[i][0] - tokens[cand][0] > max_span:
            continue
        if k >= 3 or (k == 2 and run_similarity(tokens, cand, i) >= SIMILAR_RUN_RATIO):
            confidence: Confidence = "high"
        elif k == 2 or (len(after[0]) >= 4 and i - cand <= LOW_REPEAT_MAX_RUN):
            confidence = "low"
        else:
            continue
        if confidence == "high":
            # Цепочка дублей: тот же зачин ещё раньше — брак начинается там.
            while True:
                lo2 = max(0, cand - REPEAT_LOOKBACK_TOKENS)
                for k2 in range(cand - 1, lo2 - 1, -1):
                    if in_marker[k2]:
                        lo2 = k2 + 1
                        break
                k_prev, rel_prev = best_match([norm(t[2]) for t in tokens[lo2:cand]], after)
                if k_prev < 2 or tokens[i][0] - tokens[lo2 + rel_prev][0] > max_span:
                    break
                cand = lo2 + rel_prev
        start = _span_start(tokens, cand)
        end = max(start + EPS, min(duration, tokens[i][0] - LEAD_SEC))
        out.append(
            Retake(
                start=start,
                end=end,
                reason="repeat",
                confidence=confidence,
                marker=None,
                before=_text(tokens, cand, i),
                after=_text(tokens, i, len(tokens), limit=6),
            )
        )
    return _dedupe(out)


def _dedupe(items: list[Retake]) -> list[Retake]:
    """Пересечения: уверенный поглощает неуверенного, два уверенных сливаются,
    неуверенный внутри другого — отбрасывается."""
    out: list[Retake] = []
    for cand in sorted(items, key=lambda r: (r.start, r.end)):
        if not out or cand.start >= out[-1].end - EPS:
            out.append(cand)
            continue
        last = out[-1]
        if cand.confidence == "high" and last.confidence == "low":
            out[-1] = cand
        elif cand.confidence == "high" and last.confidence == "high":
            out[-1] = Retake(
                start=last.start,
                end=max(last.end, cand.end),
                reason=last.reason if last.reason == "marker" else cand.reason,
                confidence="high",
                marker=last.marker or cand.marker,
                before=last.before,
                after=cand.after,
            )
        # cand low и пересекается с чем-то — отбрасываем.
    return out


def high_confidence_cuts(items: list[Retake]) -> list[tuple[float, float]]:
    return [(r.start, r.end) for r in items if r.confidence == "high"]

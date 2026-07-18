"""Скоринг тестов (Ф3b). Pure — без БД.

Снапшот попытки = вопросы КАК ПРЕДЪЯВЛЕНЫ (детерминированный shuffle по
seed): правка вопросов автором не ломает начатые попытки, HR ревьюит
именно то, что видел сотрудник, резюм попытки воспроизводит тот же порядок.

Типо-специфичный shuffle (adversarial-ревью плана):
- single/multi: перемешиваются варианты (correct-индексы переиндексируются);
- match: перемешивается ТОЛЬКО правая колонка (левая — заданный порядок);
- order: элементы предъявляются перемешанными ВСЕГДА (иначе правильный
  порядок совпадает с предъявленным и ответ очевиден);
- open: как есть.

Форматы ответов сотрудника (answers[question_id]):
- single: int — индекс предъявленного варианта;
- multi:  list[int];
- match:  list[int] длины len(left) — для каждого левого индекс правого;
- order:  list[int] — предъявленные индексы в выбранном порядке;
- open:   str.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

WEIGHT_RETRY_KEY = "quiz.passed_retry"


def build_snapshot(
    questions: list[dict[str, Any]],
    *,
    shuffle_questions: bool,
    shuffle_options: bool,
    seed: int,
) -> list[dict[str, Any]]:
    """Вопросы (dict с id/qtype/prompt/media_id/options/answer/points) →
    снапшот предъявления. answer в снапшоте ПЕРЕИНДЕКСИРОВАН под shuffle."""
    rng = random.Random(seed)  # noqa: S311 — не криптография, детерминизм предъявления
    snap = [dict(q) for q in questions]
    if shuffle_questions:
        rng.shuffle(snap)

    out = []
    for q in snap:
        qtype = q["qtype"]
        options = dict(q.get("options") or {})
        answer = dict(q["answer"]) if q.get("answer") else None

        if qtype in ("single", "multi"):
            opts = list(options.get("options") or [])
            order = list(range(len(opts)))
            if shuffle_options:
                rng.shuffle(order)
            options["options"] = [opts[i] for i in order]
            if answer and "correct" in answer:
                # старый индекс → новый (позиция в предъявленном списке)
                new_index = {old: new for new, old in enumerate(order)}
                answer["correct"] = sorted(new_index[i] for i in answer["correct"])
        elif qtype == "match":
            right = list(options.get("right") or [])
            order = list(range(len(right)))
            if shuffle_options:
                rng.shuffle(order)
            options["right"] = [right[i] for i in order]
            if answer and "pairs" in answer:
                new_index = {old: new for new, old in enumerate(order)}
                answer["pairs"] = [
                    [left_i, new_index[right_i]] for left_i, right_i in answer["pairs"]
                ]
        elif qtype == "order":
            items = list(options.get("items") or [])
            order = list(range(len(items)))
            # Перемешиваем всегда; гарантируем «не правильный порядок».
            for _ in range(10):
                rng.shuffle(order)
                if order != list(range(len(items))) or len(items) < 2:
                    break
            options["items"] = [items[i] for i in order]
            # Правильная последовательность в терминах ПРЕДЪЯВЛЕННЫХ индексов.
            new_index = {old: new for new, old in enumerate(order)}
            answer = {"order": [new_index[i] for i in range(len(items))]}

        out.append(
            {
                "id": str(q["id"]),
                "qtype": qtype,
                "prompt": q["prompt"],
                "media_id": str(q["media_id"]) if q.get("media_id") else None,
                "options": options,
                "answer": answer,
                "points": int(q.get("points") or 1),
            }
        )
    return out


def sanitize_snapshot(snapshot: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Копия снапшота без правильных ответов — для выдачи сотруднику."""
    return [{k: v for k, v in q.items() if k != "answer"} for q in snapshot]


@dataclass
class ScoreResult:
    auto_points: float = 0.0
    max_points: float = 0.0
    open_question_ids: list[str] = field(default_factory=list)
    per_question: dict[str, bool | None] = field(default_factory=dict)  # None = review


def _is_correct(q: dict[str, Any], value: Any) -> bool:
    qtype = q["qtype"]
    answer = q.get("answer") or {}
    try:
        if qtype == "single":
            return isinstance(value, int) and [value] == list(answer.get("correct") or [])
        if qtype == "multi":
            if not isinstance(value, list):
                return False
            return sorted(int(v) for v in value) == sorted(answer.get("correct") or [])
        if qtype == "match":
            pairs = {
                int(left_i): int(right_i)
                for left_i, right_i in (answer.get("pairs") or [])
            }
            if not isinstance(value, list) or len(value) != len(pairs):
                return False
            return all(pairs.get(i) == int(v) for i, v in enumerate(value))
        if qtype == "order":
            want = list(answer.get("order") or [])
            return isinstance(value, list) and [int(v) for v in value] == want
    except (TypeError, ValueError):
        return False
    return False


def score_attempt(
    snapshot: list[dict[str, Any]], answers: dict[str, Any]
) -> ScoreResult:
    """Авто-скоринг закрытых вопросов; open с непустым ответом → на ревью,
    open без ответа → 0 (ревьюить нечего)."""
    result = ScoreResult()
    for q in snapshot:
        qid = q["id"]
        pts = float(q.get("points") or 1)
        result.max_points += pts
        value = answers.get(qid)
        if q["qtype"] == "open":
            if isinstance(value, str) and value.strip():
                result.open_question_ids.append(qid)
                result.per_question[qid] = None
            else:
                result.per_question[qid] = False
            continue
        ok = _is_correct(q, value)
        result.per_question[qid] = ok
        if ok:
            result.auto_points += pts
    return result


def finalize(
    snapshot: list[dict[str, Any]],
    auto_points: float,
    review_scores: dict[str, float] | None,
    pass_score_pct: int,
) -> tuple[int, bool]:
    """→ (score_pct, passed). review_scores клампится в [0, points вопроса]."""
    max_points = sum(float(q.get("points") or 1) for q in snapshot)
    by_id = {q["id"]: float(q.get("points") or 1) for q in snapshot}
    reviewed = 0.0
    for qid, score in (review_scores or {}).items():
        if qid in by_id:
            reviewed += max(0.0, min(float(score), by_id[qid]))
    if max_points <= 0:
        return 0, False
    pct = round((auto_points + reviewed) / max_points * 100)
    return pct, pct >= pass_score_pct

"""Юнит-тесты quiz_scoring: снапшот с shuffle по seed + скоринг 5 типов."""

from __future__ import annotations

from uuid import uuid4

from app.services.quiz_scoring import (
    build_snapshot,
    finalize,
    sanitize_snapshot,
    score_attempt,
)


def _q_single(correct: int = 1, points: int = 1) -> dict:
    return {
        "id": uuid4(),
        "qtype": "single",
        "prompt": "Выберите верное",
        "media_id": None,
        "options": {"options": ["А", "Б", "В"]},
        "answer": {"correct": [correct]},
        "points": points,
    }


def _q_multi() -> dict:
    return {
        "id": uuid4(),
        "qtype": "multi",
        "prompt": "Отметьте все верные",
        "media_id": None,
        "options": {"options": ["1", "2", "3", "4"]},
        "answer": {"correct": [0, 2]},
        "points": 2,
    }


def _q_match() -> dict:
    return {
        "id": uuid4(),
        "qtype": "match",
        "prompt": "Сопоставьте",
        "media_id": None,
        "options": {"left": ["Латте", "Эспрессо"], "right": ["250 мл", "30 мл"]},
        "answer": {"pairs": [[0, 0], [1, 1]]},
        "points": 1,
    }


def _q_order() -> dict:
    return {
        "id": uuid4(),
        "qtype": "order",
        "prompt": "Расставьте по порядку",
        "media_id": None,
        "options": {"items": ["Помыть руки", "Надеть перчатки", "Собрать заказ"]},
        "answer": None,
        "points": 1,
    }


def _q_open() -> dict:
    return {
        "id": uuid4(),
        "qtype": "open",
        "prompt": "Опишите своими словами",
        "media_id": None,
        "options": {},
        "answer": None,
        "points": 3,
    }


class TestBuildSnapshot:
    def test_deterministic_by_seed(self):
        qs = [_q_single(), _q_multi(), _q_order()]
        a = build_snapshot(qs, shuffle_questions=True, shuffle_options=True, seed=42)
        b = build_snapshot(qs, shuffle_questions=True, shuffle_options=True, seed=42)
        assert a == b
        c = build_snapshot(qs, shuffle_questions=True, shuffle_options=True, seed=43)
        assert [q["id"] for q in a] != [q["id"] for q in c] or a != c

    def test_single_correct_reindexed(self):
        q = _q_single(correct=1)  # «Б»
        snap = build_snapshot([q], shuffle_questions=False, shuffle_options=True, seed=7)
        presented = snap[0]["options"]["options"]
        new_correct = snap[0]["answer"]["correct"][0]
        assert presented[new_correct] == "Б"

    def test_match_shuffles_only_right(self):
        q = _q_match()
        snap = build_snapshot([q], shuffle_questions=False, shuffle_options=True, seed=3)
        assert snap[0]["options"]["left"] == ["Латте", "Эспрессо"]  # левая как есть
        pairs = dict(map(tuple, snap[0]["answer"]["pairs"]))
        right = snap[0]["options"]["right"]
        assert right[pairs[0]] == "250 мл"
        assert right[pairs[1]] == "30 мл"

    def test_order_answer_maps_presented_indices(self):
        q = _q_order()
        snap = build_snapshot([q], shuffle_questions=False, shuffle_options=True, seed=5)
        items = snap[0]["options"]["items"]
        order = snap[0]["answer"]["order"]
        restored = [items[i] for i in order]
        assert restored == ["Помыть руки", "Надеть перчатки", "Собрать заказ"]

    def test_sanitize_strips_answers(self):
        snap = build_snapshot(
            [_q_single(), _q_match()], shuffle_questions=False, shuffle_options=True, seed=1
        )
        for q in sanitize_snapshot(snap):
            assert "answer" not in q


class TestScoreAttempt:
    def _snap(self, *qs: dict) -> list[dict]:
        # Без shuffle: индексы предсказуемы.
        return build_snapshot(list(qs), shuffle_questions=False, shuffle_options=False, seed=1)

    def test_single_correct_and_wrong(self):
        q = _q_single(correct=2)
        snap = self._snap(q)
        qid = snap[0]["id"]
        assert score_attempt(snap, {qid: 2}).auto_points == 1
        assert score_attempt(snap, {qid: 0}).auto_points == 0

    def test_multi_set_equality(self):
        snap = self._snap(_q_multi())
        qid = snap[0]["id"]
        assert score_attempt(snap, {qid: [2, 0]}).auto_points == 2  # порядок не важен
        assert score_attempt(snap, {qid: [0]}).auto_points == 0  # частично ≠ верно
        assert score_attempt(snap, {qid: [0, 2, 3]}).auto_points == 0

    def test_match_full_mapping(self):
        snap = self._snap(_q_match())
        qid = snap[0]["id"]
        assert score_attempt(snap, {qid: [0, 1]}).auto_points == 1
        assert score_attempt(snap, {qid: [1, 0]}).auto_points == 0

    def test_order_sequence(self):
        # order всегда перемешан — восстановим правильную последовательность.
        snap = build_snapshot(
            [_q_order()], shuffle_questions=False, shuffle_options=True, seed=9
        )
        qid = snap[0]["id"]
        want = snap[0]["answer"]["order"]
        assert score_attempt(snap, {qid: want}).auto_points == 1
        assert score_attempt(snap, {qid: list(reversed(want))}).auto_points == 0

    def test_open_with_answer_goes_to_review(self):
        snap = self._snap(_q_open(), _q_single())
        open_id, single_id = snap[0]["id"], snap[1]["id"]
        result = score_attempt(snap, {open_id: "мой развёрнутый ответ", single_id: 1})
        assert result.open_question_ids == [open_id]
        assert result.per_question[open_id] is None
        assert result.auto_points == 1
        assert result.max_points == 4  # 3 + 1

    def test_open_empty_scores_zero_without_review(self):
        snap = self._snap(_q_open())
        result = score_attempt(snap, {})
        assert result.open_question_ids == []
        assert result.per_question[snap[0]["id"]] is False

    def test_garbage_answers_not_crash(self):
        snap = self._snap(_q_single(), _q_multi(), _q_match())
        answers = {snap[0]["id"]: "x", snap[1]["id"]: 5, snap[2]["id"]: [[1]]}
        assert score_attempt(snap, answers).auto_points == 0


class TestFinalize:
    def test_pass_threshold(self):
        snap = build_snapshot(
            [_q_single(), _q_single()], shuffle_questions=False, shuffle_options=False, seed=1
        )
        assert finalize(snap, 2, None, 80) == (100, True)
        assert finalize(snap, 1, None, 80) == (50, False)
        assert finalize(snap, 1, None, 50) == (50, True)

    def test_review_scores_clamped(self):
        snap = build_snapshot(
            [_q_open()], shuffle_questions=False, shuffle_options=False, seed=1
        )
        qid = snap[0]["id"]
        # HR поставил больше максимума — клампится к 3 из 3.
        assert finalize(snap, 0, {qid: 99}, 80) == (100, True)
        assert finalize(snap, 0, {qid: -5}, 80) == (0, False)
        assert finalize(snap, 0, {qid: 1.5}, 50) == (50, True)

    def test_unknown_review_qid_ignored(self):
        snap = build_snapshot(
            [_q_single()], shuffle_questions=False, shuffle_options=False, seed=1
        )
        assert finalize(snap, 1, {"nope": 100}, 80) == (100, True)

"""derive_quiz_state — единый источник состояния обязательного теста для гейта
урока и раннера (ОС 2026-08: «тест не пройден, а пускает дальше»)."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from app.services.quiz_gate import QUIZ_GATE_MESSAGES, derive_quiz_state

_T = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


def _a(*, finished=True, passed=None, needs_review=False, reviewed=False):
    return SimpleNamespace(
        finished_at=_T if finished else None,
        passed=passed,
        needs_review=needs_review,
        reviewed_at=_T if reviewed else None,
    )


def test_states_in_priority_order() -> None:
    assert derive_quiz_state([], None) == "not_started"
    assert derive_quiz_state([_a(finished=False)], None) == "in_progress"
    assert derive_quiz_state([_a(passed=False)], None) == "failed"
    assert derive_quiz_state([_a(passed=False), _a(passed=True)], None) == "passed"
    assert derive_quiz_state([_a(passed=None, needs_review=True)], None) == "pending_review"
    # Проверенная open-попытка с провалом — failed, не pending.
    assert derive_quiz_state([_a(passed=False, needs_review=True, reviewed=True)], None) == "failed"
    # Лимит: две проваленные из двух — тупик; сданная побеждает лимит.
    assert derive_quiz_state([_a(passed=False), _a(passed=False)], 2) == "limit_exhausted"
    assert derive_quiz_state([_a(passed=False), _a(passed=True)], 2) == "passed"
    # Незаконченная попытка при исчерпанном лимите — всё ещё in_progress.
    assert derive_quiz_state([_a(passed=False), _a(finished=False)], 1) == "in_progress"


def test_messages_cover_every_blocking_state() -> None:
    for state in ("not_started", "in_progress", "failed", "pending_review", "limit_exhausted"):
        assert QUIZ_GATE_MESSAGES[state]

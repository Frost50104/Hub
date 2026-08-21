"""Сводка ассистента: `lines` = bullets, `content` = лид/итог без bullet-строк
(иначе фронт показывал сводку дважды — QA-0821 #17)."""

from __future__ import annotations

from app.services.assistant.runner import _extract_bullets, _strip_bullets

_TEXT = """Итого на планёрку — 3 пункта:

- KEY-1 ждёт согласования
* KEY-2 просрочена на 2 дня
• KEY-3 без исполнителя


Всего открыто 12 задач."""


def test_extract_bullets_all_markers() -> None:
    assert _extract_bullets(_TEXT) == [
        "KEY-1 ждёт согласования",
        "KEY-2 просрочена на 2 дня",
        "KEY-3 без исполнителя",
    ]


def test_strip_bullets_keeps_lead_and_footer() -> None:
    assert _strip_bullets(_TEXT) == (
        "Итого на планёрку — 3 пункта:\n\nВсего открыто 12 задач."
    )


def test_strip_bullets_without_bullets_is_identity() -> None:
    assert _strip_bullets("Просто ответ.\nВторая строка.") == "Просто ответ.\nВторая строка."
    assert _strip_bullets("- только пункты\n- и всё") == ""

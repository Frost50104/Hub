"""Unit tests for `app.services.search_dsl.parse`.

Verifies the documented surface: free text, quoted phrases, field:value
equality, date operators (<, >, =), unknown fields stay in text, malformed
values stay in text, last-write-wins on duplicates.
"""

from __future__ import annotations

from datetime import date

from app.services.search_dsl import parse


def test_empty_string_is_empty_query() -> None:
    out = parse("")
    assert out.text == ""
    assert not out.has_filters


def test_only_text_passes_through() -> None:
    out = parse("проверить договор")
    assert out.text == "проверить договор"
    assert not out.has_filters


def test_quoted_phrase_keeps_spaces() -> None:
    out = parse('"договор на услуги"')
    assert out.text == "договор на услуги"


def test_assignee_me() -> None:
    out = parse("assignee:me")
    assert out.assignee == "me"
    assert out.text == ""


def test_assignee_uuid() -> None:
    uid = "550e8400-e29b-41d4-a716-446655440000"
    out = parse(f"assignee:{uid}")
    assert out.assignee == uid


def test_status_valid() -> None:
    assert parse("status:in_progress").status == "in_progress"
    assert parse("status:done").status == "done"


def test_status_invalid_falls_to_text() -> None:
    out = parse("status:wat")
    assert out.status is None
    assert "status:wat" in out.text


def test_priority_valid() -> None:
    out = parse("priority:urgent")
    assert out.priority == "urgent"


def test_due_lt_date() -> None:
    out = parse("due:<2026-06-01")
    assert out.due_op == "<"
    assert out.due_date == date(2026, 6, 1)


def test_due_gt_date() -> None:
    out = parse("due:>2026-07-01")
    assert out.due_op == ">"
    assert out.due_date == date(2026, 7, 1)


def test_due_default_op_is_equality() -> None:
    out = parse("due:2026-05-29")
    assert out.due_op == "="
    assert out.due_date == date(2026, 5, 29)


def test_due_malformed_falls_to_text() -> None:
    out = parse("due:tomorrow")
    assert out.due_date is None
    assert "due:tomorrow" in out.text


def test_created_dates() -> None:
    out = parse("created:>2026-01-01")
    assert out.created_op == ">"
    assert out.created_date == date(2026, 1, 1)


def test_combined_filters_and_text() -> None:
    out = parse('assignee:me status:in_progress "договор на услуги"')
    assert out.assignee == "me"
    assert out.status == "in_progress"
    assert out.text == "договор на услуги"


def test_last_assignee_wins() -> None:
    out = parse("assignee:me assignee:550e8400-e29b-41d4-a716-446655440000")
    assert out.assignee == "550e8400-e29b-41d4-a716-446655440000"


def test_unknown_field_kept_in_text() -> None:
    out = parse("asignee:me")  # typo
    assert out.assignee is None
    assert "asignee:me" in out.text


def test_text_with_filters_in_any_order() -> None:
    out = parse("договор assignee:me и status:in_progress")
    assert out.assignee == "me"
    assert out.status == "in_progress"
    # Free words appear in order; filters are stripped out.
    assert "договор" in out.text and "и" in out.text


def test_assignee_with_operator_falls_back() -> None:
    # `assignee:<UUID` is meaningless — gets dropped to text.
    out = parse("assignee:<550e8400-e29b-41d4-a716-446655440000")
    assert out.assignee is None
    assert "assignee:" in out.text

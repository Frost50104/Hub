"""Связка двух проходов переноса из WEEEK.

Проходы разнесены на недели, и связывает их не файл, а два свойства:
детерминированный id (задачу можно найти по её номеру в WEEEK) и ровно
воспроизводимое описание (проход 2 узнаёт текст, который записал проход 1,
и только тогда решается снять сноску об исполнителе).
"""

from __future__ import annotations

from uuid import UUID

from app.jobs.weeek_common import (
    DESCRIPTION_MAX,
    KIND_PROJECT,
    KIND_TASK,
    assignee_note,
    compose_description,
    hub_id,
    notes_for,
    strip_assignee_note,
)

TENANT = UUID("ef0d87ef-68a6-49eb-9ecd-6a443b517c35")
OTHER = UUID("bff66a2e-1dc1-4d5c-9b72-0fcd492f95ee")


class TestIds:
    def test_deterministic(self):
        assert hub_id(TENANT, KIND_TASK, 52295) == hub_id(TENANT, KIND_TASK, 52295)

    def test_tenant_separates(self):
        # staging и прод держат один и тот же тенант uppetit в разных базах,
        # а тестовый uppetit-staging — другой; id не должны пересекаться.
        assert hub_id(TENANT, KIND_TASK, 1) != hub_id(OTHER, KIND_TASK, 1)

    def test_kind_separates(self):
        assert hub_id(TENANT, KIND_TASK, 1) != hub_id(TENANT, KIND_PROJECT, 1)

    def test_int_and_str_key_agree(self):
        assert hub_id(TENANT, KIND_TASK, 1) == hub_id(TENANT, KIND_TASK, "1")


class TestAssigneeNote:
    def test_singular_and_plural(self):
        assert assignee_note(["Иван"]) == "_Исполнитель в WEEEK: Иван_"
        assert assignee_note(["Иван", "Пётр"]) == "_Исполнители в WEEEK: Иван, Пётр_"

    def test_empty(self):
        assert assignee_note([]) is None
        assert assignee_note(["", "  "]) is None

    def test_underscores_in_name_do_not_break_italics(self):
        assert assignee_note(["А_Б"]) == "_Исполнитель в WEEEK: А Б_"


class TestCompose:
    def test_no_notes_keeps_body_untouched(self):
        # У 13 тысяч задач из 16 703 терять нечего — описание остаётся как было.
        assert compose_description("Тело", weeek_id=1) == "Тело"
        assert compose_description(None, weeek_id=1) is None

    def test_block_order_is_fixed_and_assignee_is_last(self):
        text = compose_description(
            "Тело",
            weeek_id=52295,
            parent_note="Подзадача.",
            attachments_note="Вложения в WEEEK: a.pdf.",
            assignee_note_text=assignee_note(["Иван"]),
        )
        assert text.splitlines() == [
            "Тело",
            "",
            "---",
            "Перенесено из WEEEK (задача 52295).",
            "Подзадача.",
            "Вложения в WEEEK: a.pdf.",
            "_Исполнитель в WEEEK: Иван_",
        ]

    def test_body_may_be_empty(self):
        text = compose_description(None, weeek_id=7, assignee_note_text=assignee_note(["И"]))
        assert text.startswith("---")

    def test_result_fits_the_api_limit(self):
        # Сервер обязан отдавать значение, которое сам же примет обратно:
        # иначе первая правка описания в UI получит 422.
        text = compose_description(
            "я" * 25_000, weeek_id=1, assignee_note_text=assignee_note(["Иван"])
        )
        assert len(text) <= DESCRIPTION_MAX
        assert text.endswith("_Исполнитель в WEEEK: Иван_")


class TestRoundTrip:
    def _pair(self) -> tuple[str, str]:
        kw = {"weeek_id": 52295, "parent_note": "Подзадача.",
              "attachments_note": "Вложения в WEEEK: a.pdf."}
        with_note = compose_description(
            "Тело", assignee_note_text=assignee_note(["Иван"]), **kw
        )
        without = compose_description("Тело", **kw)
        return with_note, without

    def test_strip_returns_exactly_the_clean_version(self):
        with_note, without = self._pair()
        assert strip_assignee_note(with_note) == (without, True)

    def test_strip_is_idempotent(self):
        _with, without = self._pair()
        assert strip_assignee_note(without) == (without, False)

    def test_strip_ignores_similar_text_inside_the_body(self):
        # Фраза в теле задачи не должна приниматься за сноску.
        body = "Исполнитель в WEEEK: Иван — уточнить у него"
        text = compose_description(body, weeek_id=1, parent_note="Подзадача.")
        assert strip_assignee_note(text) == (text, False)

    def test_strip_handles_none_and_empty(self):
        assert strip_assignee_note(None) == (None, False)
        assert strip_assignee_note("") == ("", False)

    def test_note_only_description_becomes_none_after_strip(self):
        text = compose_description(None, weeek_id=1, assignee_note_text=assignee_note(["И"]))
        stripped, removed = strip_assignee_note(text)
        assert removed
        assert stripped.endswith("(задача 1).")


class TestNotes:
    def test_cross_project_gets_a_link(self):
        parent, attachments = notes_for(
            {"parent_ref": {"kind": "cross_project", "weeek_id": 900,
                            "title": "Открытие точки", "project_weeek_id": 42}},
            TENANT,
        )
        assert "Подзадача задачи «Открытие точки»" in parent
        assert f"/projects/{hub_id(TENANT, KIND_PROJECT, 42)}" in parent
        assert f"?task={hub_id(TENANT, KIND_TASK, 900)}" in parent
        assert attachments is None

    def test_orphan_has_no_link(self):
        parent, _ = notes_for(
            {"parent_ref": {"kind": "orphan", "weeek_id": 1, "title": "Т",
                            "project_weeek_id": None}},
            TENANT,
        )
        assert "родитель не перенесён" in parent
        assert "/projects/" not in parent

    def test_flattened_says_so(self):
        parent, _ = notes_for(
            {"parent_ref": {"kind": "flattened", "weeek_id": 5, "title": "Т",
                            "project_weeek_id": 42}},
            TENANT,
        )
        assert parent.startswith("В WEEEK была подзадачей задачи")

    def test_attachment_names(self):
        _parent, attachments = notes_for({"attachment_names_only": ["a.pdf", "b.mov"]}, TENANT)
        assert attachments == "Вложения в WEEEK: a.pdf, b.mov."

    def test_nothing(self):
        assert notes_for({}, TENANT) == (None, None)

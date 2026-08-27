"""Маппинг WEEEK → Hub: детерминизм и четыре ветки подзадач.

Главное требование к этому модулю — повторный прогон сборщика на тех же
ответах API обязан дать те же `seq`, позиции и ключи. Иначе повторный импорт
переставит карточки, а проход 2 не найдёт задачу.
"""

from __future__ import annotations

from datetime import date

from tools.import_weeek.mapping import (
    ParentDecision,
    day_of,
    key_hint,
    merge_sections,
    merge_stages,
    normalize_stage_name,
    priority_of,
    resolve_parents,
    root_portfolio,
    task_sort_key,
)


class TestPriority:
    def test_scale(self):
        assert [priority_of(i) for i in (0, 1, 2, 3)] == ["low", "medium", "high", "urgent"]

    def test_missing_is_medium(self):
        # 98% задач WEEEK без приоритета; medium — дефолт Hub.
        assert priority_of(None) == "medium"
        assert priority_of("high") == "medium"
        assert priority_of(9) == "medium"

    def test_bool_is_not_an_int_here(self):
        # True == 1 в Python; молча стать «medium» безопаснее, чем угадывать.
        assert priority_of(True) == "medium"


class TestProjectKey:
    def test_real_names(self):
        assert key_hint("Подбор линейного персонала") == "PLP"
        assert key_hint("Локальный маркетинг") == "LM"
        assert key_hint("Бухгалтерия Аппетит") == "BA"
        assert key_hint("Ввод/вывод сотрудников") == "VVS"

    def test_single_word_is_transliterated_not_initialed(self):
        # generate_unique_key даёт здесь однобуквенный «D» (см. tech-debt).
        assert key_hint("Дизайн") == "DIZAYN"
        assert key_hint("Мониторы") == "MONITORY"

    def test_stop_words_are_dropped_before_translit(self):
        # После транслита «на» это уже «NA», и русский стоп-список молчал бы.
        assert key_hint("Поход на кофе 3 точки") == "PKT"

    def test_format_and_length_hold_for_any_input(self):
        import re

        for name in ("-18", "", "🙂", "СЕРМ/ОРМ", "а", "Отдел " * 20):
            key = key_hint(name)
            assert re.fullmatch(r"[A-Z][A-Z0-9]*", key), key
            assert len(key) <= 12

    def test_deterministic(self):
        assert key_hint("Локальный маркетинг") == key_hint("Локальный маркетинг")


class TestStages:
    def _boards(self) -> list[dict]:
        # Реальная форма «Ввод/вывод сотрудников»: своя доска плюс двенадцать
        # одинаковых, по доске на сотрудника.
        same = [{"id": 100 + i, "name": f"Доска {i}", "columns": [
            {"id": 1000 + i * 10 + j, "name": n}
            for j, n in enumerate(("К работе", "В работе", "Готово"))
        ]} for i in range(12)]
        first = {"id": 99, "name": "Ввод/вывод", "columns": [
            {"id": 900, "name": "Илья"}, {"id": 901, "name": "Никита"},
        ]}
        return [first, *same]

    def test_identical_columns_merge(self):
        stages, by_column = merge_stages(self._boards())
        assert [s.name for s in stages] == ["Илья", "Никита", "К работе", "В работе", "Готово"]
        assert [s.position for s in stages] == [0, 1, 2, 3, 4]
        # Колонка каждой из 12 досок ведёт в один и тот же этап.
        assert by_column[1000] == by_column[1110] == normalize_stage_name("К работе")

    def test_case_and_spaces_do_not_split_a_stage(self):
        boards = [{"id": 1, "name": "b", "columns": [
            {"id": 10, "name": "Готово"}, {"id": 11, "name": " готово "},
        ]}]
        stages, by_column = merge_stages(boards)
        assert len(stages) == 1
        assert stages[0].name == "Готово"  # первое написание группы
        assert by_column[10] == by_column[11]

    def test_empty_column_names_are_skipped(self):
        stages, by_column = merge_stages([{"id": 1, "columns": [{"id": 10, "name": "  "}]}])
        assert stages == []
        assert by_column == {}

    def test_unknown_column_leaves_the_task_without_a_stage(self):
        """Удалённая в WEEEK колонка — это «без статуса», а не первая по счёту.

        Сваливать такие задачи в «К работе» значило бы соврать: имя колонки
        читают глазами. Синтетической колонки-приёмника тоже нет (0046).
        """
        _stages, by_column = merge_stages(
            [{"id": 1, "columns": [{"id": 10, "name": "Готово"}]}]
        )
        assert by_column.get(999) is None


class TestSections:
    def test_single_board_gives_no_sections(self):
        # Доска называется как проект — секция была бы шумом (42 проекта из 47).
        assert merge_sections([{"id": 1, "name": "Дизайн", "columns": []}]) == []

    def test_several_boards_become_sections(self):
        sections = merge_sections([
            {"id": 7, "name": "Алена", "columns": []},
            {"id": 8, "name": "Юля", "columns": []},
        ])
        assert [(s.board_id, s.name, s.position) for s in sections] == [
            (7, "Алена", 0), (8, "Юля", 1)
        ]


class TestPortfolios:
    def _tree(self) -> dict[int, dict]:
        return {
            19: {"id": 19, "name": "Отдел Персонала", "parentId": None},
            8: {"id": 8, "name": "Лояльность", "parentId": 19},
            5: {"id": 5, "name": "Глубже", "parentId": 8},
        }

    def test_nested_portfolio_collapses_to_root(self):
        # Папки в Hub — ровно один уровень.
        assert root_portfolio(self._tree(), 5)["id"] == 19
        assert root_portfolio(self._tree(), 19)["id"] == 19

    def test_no_portfolio(self):
        assert root_portfolio(self._tree(), None) is None
        assert root_portfolio(self._tree(), 404) is None

    def test_cycle_does_not_hang(self):
        tree = {1: {"id": 1, "parentId": 2}, 2: {"id": 2, "parentId": 1}}
        assert root_portfolio(tree, 1) is not None


class TestDates:
    def test_plain_date_wins(self):
        assert day_of("2026-08-26", None) == date(2026, 8, 26)

    def test_instant_is_converted_to_display_day(self):
        # Воркспейс WEEEK стоит в Europe/Podgorica, Hub показывает Москву:
        # 22:30 UTC — это уже следующий день по-московски.
        assert day_of(None, "2026-06-23T09:00:00Z") == date(2026, 6, 23)
        assert day_of(None, "2026-06-23T22:30:00Z") == date(2026, 6, 24)

    def test_nothing(self):
        assert day_of(None, None) is None
        assert day_of("", "") is None

    def test_garbage_does_not_raise(self):
        assert day_of("не дата", None) is None
        assert day_of(None, "не дата") is None


class TestParents:
    def _tasks(self) -> dict[int, dict]:
        return {
            1: {"id": 1, "parentId": None, "projectId": 10},   # корень
            2: {"id": 2, "parentId": 1, "projectId": 10},      # обычная подзадача
            3: {"id": 3, "parentId": 2, "projectId": 10},      # глубина 2
            4: {"id": 4, "parentId": 1, "projectId": 20},      # родитель в другом проекте
            5: {"id": 5, "parentId": 99, "projectId": 10},     # родитель не перенесён
            6: {"id": 6, "parentId": 7, "projectId": 10},      # родитель вне объёма
            7: {"id": 7, "parentId": None, "projectId": 10},
        }

    def test_all_four_branches(self):
        in_scope = {1, 2, 3, 4, 5, 6}
        out = resolve_parents(self._tasks(), in_scope)
        assert out[1] == ParentDecision(None, None, None)
        assert out[2] == ParentDecision(1, None, None)
        # Глубина 2 схлопывается к КОРНЮ: прямой родитель сам подзадача,
        # а Hub держит ровно один уровень.
        assert out[3] == ParentDecision(1, 2, "flattened")
        # Ребёнок в чужом проекте исчез бы и с доски, и из карточки родителя.
        assert out[4] == ParentDecision(None, 1, "cross_project")
        assert out[5] == ParentDecision(None, 99, "orphan")
        assert out[6] == ParentDecision(None, 7, "orphan")

    def test_cycle_does_not_hang(self):
        tasks = {1: {"id": 1, "parentId": 2, "projectId": 10},
                 2: {"id": 2, "parentId": 1, "projectId": 10}}
        out = resolve_parents(tasks, {1, 2})
        assert set(out) == {1, 2}


class TestOrder:
    def test_stable_by_created_then_id(self):
        rows = [
            {"id": 5, "createdAt": "2026-01-02T00:00:00Z"},
            {"id": 3, "createdAt": "2026-01-01T00:00:00Z"},
            {"id": 4, "createdAt": "2026-01-01T00:00:00Z"},
        ]
        assert [t["id"] for t in sorted(rows, key=task_sort_key)] == [3, 4, 5]

    def test_missing_created_sorts_first_but_stably(self):
        rows = [{"id": 2, "createdAt": None}, {"id": 1, "createdAt": None}]
        assert [t["id"] for t in sorted(rows, key=task_sort_key)] == [1, 2]

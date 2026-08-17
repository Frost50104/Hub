"""Конвертер Quill → RichDoc: фикстуры взяты из реальной выгрузки ServiceGuru.

Каждый результат прогоняется через СЕРВЕРНЫЙ валидатор урока — конвертер и
whitelist Hub должны сходиться (иначе импорт упадёт на VPS, а не здесь).
"""

from __future__ import annotations

import pytest

from app.services.lesson_content import validate_lesson_content
from tools.import_lms.quill_to_richdoc import html_to_plain, quill_to_nodes


def _valid(nodes: list[dict]) -> list[dict]:
    validate_lesson_content({"schema": 1, "doc": {"type": "doc", "content": nodes}})
    return nodes


def test_bold_with_color_becomes_two_marks():
    nodes = _valid(quill_to_nodes('<p><b style="color: rgb(230, 0, 0);">Важно</b></p>'))
    marks = nodes[0]["content"][0]["marks"]
    assert {"type": "bold"} in marks
    assert {"type": "textStyle", "attrs": {"color": "#e60000"}} in marks


def test_currentcolor_and_transparent_dropped():
    html = (
        '<p><span style="color: currentcolor;">а</span>'
        '<span style="background-color: transparent;">б</span></p>'
    )
    nodes = _valid(quill_to_nodes(html))
    assert nodes[0]["content"] == [{"type": "text", "text": "аб"}]


def test_nbsp_normalized():
    nodes = _valid(quill_to_nodes("<p>Текст с nbsp</p>"))
    assert nodes[0]["content"][0]["text"] == "Текст с nbsp"


def test_empty_paragraphs_collapse():
    html = "<p>А</p><p><br></p><p><br></p><p>Б</p><p><br></p>"
    nodes = _valid(quill_to_nodes(html))
    types = [(n["type"], bool(n.get("content"))) for n in nodes]
    # Между абзацами остаётся ровно один пустой, хвостовой отброшен.
    assert types == [("paragraph", True), ("paragraph", False), ("paragraph", True)]


def test_list_item_always_wraps_paragraph():
    """TipTap нормализует listItem без paragraph — оборачиваем сами."""
    nodes = _valid(quill_to_nodes("<ul><li>пункт</li></ul>"))
    item = nodes[0]["content"][0]
    assert nodes[0]["type"] == "bulletList"
    assert item["content"][0]["type"] == "paragraph"


def test_ordered_list_strips_duplicated_numbering():
    nodes = _valid(quill_to_nodes("<ol><li>1. Первый</li><li>2. Второй</li></ol>"))
    texts = [i["content"][0]["content"][0]["text"] for i in nodes[0]["content"]]
    assert texts == ["Первый", "Второй"]


def test_quill2_data_list_overrides_tag():
    """Quill 2 кодирует тип списка в li[data-list], а не тегом."""
    nodes = _valid(quill_to_nodes('<ol><li data-list="bullet">пункт</li></ol>'))
    assert nodes[0]["type"] == "bulletList"


@pytest.mark.parametrize(
    ("href", "keeps_link"),
    [
        ("https://taskuppetit.ru/", True),
        ("mailto:hr@uppetit.ru", True),
        ("javascript:alert(1)", False),
        ("ftp://files.local/x", False),
    ],
)
def test_link_scheme_whitelist(href: str, keeps_link: bool):
    nodes = _valid(quill_to_nodes(f'<p><a href="{href}">клик</a></p>'))
    marks = nodes[0]["content"][0].get("marks", [])
    assert any(m["type"] == "link" for m in marks) is keeps_link


def test_ql_cursor_artifact_removed():
    nodes = _valid(quill_to_nodes('<p>текст<span class="ql-cursor">﻿</span></p>'))
    assert nodes[0]["content"] == [{"type": "text", "text": "текст"}]


def test_ql_align_dropped_but_text_kept():
    """attrs у paragraph запрещены валидатором — выравнивание теряем осознанно."""
    nodes = _valid(quill_to_nodes('<p class="ql-align-center"><b>Центр</b></p>'))
    assert "attrs" not in nodes[0]
    assert nodes[0]["content"][0]["text"] == "Центр"


def test_ql_size_large_becomes_font_size():
    nodes = _valid(quill_to_nodes('<p><span class="ql-size-large">крупно</span></p>'))
    marks = nodes[0]["content"][0]["marks"]
    assert {"type": "textStyle", "attrs": {"fontSize": "20px"}} in marks


def test_heading_levels_clamped():
    nodes = _valid(quill_to_nodes("<h3>Три</h3><h6>Шесть</h6>"))
    assert [n["attrs"]["level"] for n in nodes] == [3, 4]


def test_br_inside_paragraph_is_hardbreak():
    nodes = _valid(quill_to_nodes("<p>первая<br>вторая</p>"))
    assert [n["type"] for n in nodes[0]["content"]] == ["text", "hardBreak", "text"]


def test_nested_marks_survive():
    html = '<p><b><em>жирный курсив</em></b></p>'
    nodes = _valid(quill_to_nodes(html))
    types = {m["type"] for m in nodes[0]["content"][0]["marks"]}
    assert types == {"bold", "italic"}


def test_html_to_plain_for_product_cards():
    html = "<p><em>Кофейный напиток.</em></p><p>На основе молока</p>"
    assert html_to_plain(html) == "Кофейный напиток.На основе молока"


def test_empty_html_gives_no_nodes():
    assert quill_to_nodes("") == []
    assert quill_to_nodes("<p><br></p>") == []

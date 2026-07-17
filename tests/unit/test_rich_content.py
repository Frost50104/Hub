"""Юнит-тесты валидатора TipTap-контента (Ф2, adversarial-ревью §10-11)."""

from __future__ import annotations

import pytest

from app.services.rich_content import (
    RichContentError,
    empty_doc,
    extract_text,
    validate_rich_content,
)


def _doc(*content) -> dict:
    return {"schema": 1, "doc": {"type": "doc", "content": list(content)}}


def _p(text: str, marks: list | None = None) -> dict:
    node: dict = {"type": "text", "text": text}
    if marks:
        node["marks"] = marks
    return {"type": "paragraph", "content": [node]}


def test_valid_document_passes():
    doc = _doc(
        {
            "type": "heading",
            "attrs": {"level": 2},
            "content": [{"type": "text", "text": "Заголовок"}],
        },
        _p("Обычный текст", marks=[{"type": "bold"}]),
        {
            "type": "callout",
            "attrs": {"kind": "important"},
            "content": [_p("Важно!")],
        },
        {
            "type": "bulletList",
            "content": [{"type": "listItem", "content": [_p("пункт")]}],
        },
    )
    assert validate_rich_content(doc) is doc


def test_unknown_node_rejected():
    with pytest.raises(RichContentError, match="запрещена"):
        validate_rich_content(_doc({"type": "iframe", "attrs": {"src": "https://x"}}))


def test_javascript_link_rejected():
    doc = _doc(
        _p("клик", marks=[{"type": "link", "attrs": {"href": "javascript:alert(1)"}}])
    )
    with pytest.raises(RichContentError, match="https/mailto/tel"):
        validate_rich_content(doc)


def test_https_link_ok():
    doc = _doc(_p("клик", marks=[{"type": "link", "attrs": {"href": "https://uppetit.ru"}}]))
    validate_rich_content(doc)


def test_heading_level_out_of_range():
    doc = _doc({"type": "heading", "attrs": {"level": 7}, "content": []})
    with pytest.raises(RichContentError, match="1..4"):
        validate_rich_content(doc)


def test_callout_unknown_kind():
    doc = _doc({"type": "callout", "attrs": {"kind": "hacker"}, "content": []})
    with pytest.raises(RichContentError, match="kind"):
        validate_rich_content(doc)


def test_depth_bomb_rejected():
    node: dict = {"type": "blockquote", "content": []}
    root = node
    for _ in range(40):
        child: dict = {"type": "blockquote", "content": []}
        node["content"] = [child]
        node = child
    with pytest.raises(RichContentError, match="вложенность"):
        validate_rich_content({"schema": 1, "doc": {"type": "doc", "content": [root]}})


def test_size_limit():
    doc = _doc(_p("x" * 600_000))
    with pytest.raises(RichContentError, match="лимита"):
        validate_rich_content(doc)


def test_bad_envelope_rejected():
    with pytest.raises(RichContentError):
        validate_rich_content({"doc": {"type": "doc"}})
    with pytest.raises(RichContentError):
        validate_rich_content({"schema": 2, "doc": {"type": "doc"}})


def test_extra_attrs_rejected():
    doc = _doc({"type": "paragraph", "attrs": {"onclick": "x"}, "content": []})
    with pytest.raises(RichContentError):
        validate_rich_content(doc)


def test_extract_text():
    doc = _doc(
        {
            "type": "heading",
            "attrs": {"level": 1},
            "content": [{"type": "text", "text": "Новость"}],
        },
        _p("Первый абзац"),
        _p("Второй"),
    )
    assert extract_text(doc) == "Новость Первый абзац Второй"


def test_empty_doc_is_valid():
    validate_rich_content(empty_doc())

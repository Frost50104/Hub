"""Серверный валидатор TipTap-JSON контента (Ф2, adversarial-ревью §10-11).

Контент хранится как `{"schema": 1, "doc": {...}}`. Валидатор — fail-closed:
- whitelist типов нод и марок (неизвестное → отказ);
- ссылки только https/mailto/tel (TipTap Link по умолчанию пропускает
  `javascript:`);
- у image (появится в Ф3a) запрещены data:/внешние src;
- жёсткий лимит сериализованного размера (вставка из Word с base64-картинками
  раздувает JSONB до мегабайт);
- ограничение глубины (защита от рекурсивных бомб).

`extract_text()` — плоский текст для поискового индекса.

Наборы нод:
- NEWS_NODES — текстовый набор (Ф2: новости);
- LESSON_NODES — расширится в Ф3a (figure/gallery/video/pdf/survey/checkQuestion).
"""

from __future__ import annotations

import json
import re
from typing import Any

MAX_BYTES_NEWS = 500_000
MAX_DEPTH = 30

_SAFE_URL = re.compile(r"^(https?://|mailto:|tel:)", re.IGNORECASE)
_COLOR = re.compile(r"^(#[0-9a-fA-F]{3,8}|rgba?\([\d\s.,%]+\)|[a-z-]{1,30})$")

CALLOUT_KINDS = frozenset(
    {"important", "warning", "tip", "mistake", "example", "recommendation"}
)

# Текстовые ноды: type -> валидатор attrs (None = attrs запрещены).
_TEXT_NODES: dict[str, Any] = {
    "doc": None,
    "paragraph": None,
    "text": None,
    "hardBreak": None,
    "horizontalRule": None,
    "blockquote": None,
    "bulletList": None,
    "orderedList": "orderedList",
    "listItem": None,
    "heading": "heading",
    "table": None,
    "tableRow": None,
    "tableCell": "tableCell",
    "tableHeader": "tableCell",
    "callout": "callout",
}

_MARKS = frozenset({"bold", "italic", "underline", "strike", "link", "textStyle", "highlight"})

NEWS_NODES = frozenset(_TEXT_NODES)


class RichContentError(ValueError):
    pass


def _check_attrs(node_type: str, attrs: dict[str, Any] | None) -> None:
    kind = _TEXT_NODES.get(node_type)
    if attrs is None:
        return
    if kind == "heading":
        level = attrs.get("level")
        if not isinstance(level, int) or not 1 <= level <= 4:
            raise RichContentError("heading: level должен быть 1..4")
        _no_extra(attrs, {"level"})
    elif kind == "callout":
        if attrs.get("kind") not in CALLOUT_KINDS:
            raise RichContentError("callout: неизвестный kind")
        _no_extra(attrs, {"kind"})
    elif kind == "orderedList":
        start = attrs.get("start", 1)
        if not isinstance(start, int) or start < 0 or start > 10_000:
            raise RichContentError("orderedList: некорректный start")
        _no_extra(attrs, {"start"})
    elif kind == "tableCell":
        for key in attrs:
            if key not in ("colspan", "rowspan", "colwidth"):
                raise RichContentError(f"table-ячейка: атрибут {key!r} запрещён")
            value = attrs[key]
            if key == "colwidth":
                if value is not None and not (
                    isinstance(value, list) and all(isinstance(x, int) for x in value)
                ):
                    raise RichContentError("colwidth: ожидается список чисел")
            elif not isinstance(value, int) or not 1 <= value <= 50:
                raise RichContentError(f"{key}: 1..50")
    elif attrs:
        raise RichContentError(f"{node_type}: атрибуты запрещены")


def _no_extra(attrs: dict[str, Any], allowed: set[str]) -> None:
    extra = set(attrs) - allowed
    if extra:
        raise RichContentError(f"лишние атрибуты: {sorted(extra)}")


def _check_mark(mark: dict[str, Any]) -> None:
    mtype = mark.get("type")
    if mtype not in _MARKS:
        raise RichContentError(f"марка {mtype!r} запрещена")
    attrs = mark.get("attrs") or {}
    if mtype == "link":
        href = attrs.get("href", "")
        if not isinstance(href, str) or not _SAFE_URL.match(href) or len(href) > 2000:
            raise RichContentError("link: разрешены только https/mailto/tel")
    elif mtype == "textStyle":
        color = attrs.get("color")
        if color is not None and (not isinstance(color, str) or not _COLOR.match(color)):
            raise RichContentError("textStyle: некорректный цвет")
    elif mtype == "highlight":
        color = attrs.get("color")
        if color is not None and (not isinstance(color, str) or not _COLOR.match(color)):
            raise RichContentError("highlight: некорректный цвет")
    elif attrs:
        raise RichContentError(f"{mtype}: атрибуты запрещены")


def _walk(node: dict[str, Any], allowed_nodes: frozenset[str], depth: int) -> None:
    if depth > MAX_DEPTH:
        raise RichContentError("слишком глубокая вложенность")
    if not isinstance(node, dict):
        raise RichContentError("нода должна быть объектом")
    ntype = node.get("type")
    if ntype not in allowed_nodes:
        raise RichContentError(f"нода {ntype!r} запрещена")
    _check_attrs(ntype, node.get("attrs"))
    for mark in node.get("marks") or []:
        _check_mark(mark)
    if ntype == "text":
        if not isinstance(node.get("text"), str):
            raise RichContentError("text: пустой текст")
        if node.get("content"):
            raise RichContentError("text: вложенный content запрещён")
        return
    content = node.get("content") or []
    if not isinstance(content, list):
        raise RichContentError("content должен быть списком")
    for child in content:
        _walk(child, allowed_nodes, depth + 1)


def validate_rich_content(
    payload: Any,
    *,
    allowed_nodes: frozenset[str] = NEWS_NODES,
    max_bytes: int = MAX_BYTES_NEWS,
) -> dict[str, Any]:
    """Проверить `{"schema": 1, "doc": {...}}`. Возвращает payload как есть."""
    if not isinstance(payload, dict) or payload.get("schema") != 1:
        raise RichContentError("ожидается {schema: 1, doc: {...}}")
    doc = payload.get("doc")
    if not isinstance(doc, dict) or doc.get("type") != "doc":
        raise RichContentError("doc: корневая нода должна быть type=doc")
    raw = json.dumps(payload, ensure_ascii=False)
    if len(raw.encode()) > max_bytes:
        raise RichContentError(
            f"контент больше лимита {max_bytes // 1000} КБ — уберите вставленные "
            "картинки/форматирование Word"
        )
    _walk(doc, allowed_nodes, 0)
    return payload


def extract_text(payload: dict[str, Any]) -> str:
    """Плоский текст для поискового индекса."""
    chunks: list[str] = []

    def walk(node: dict[str, Any]) -> None:
        if node.get("type") == "text":
            chunks.append(node.get("text", ""))
        for child in node.get("content") or []:
            if isinstance(child, dict):
                walk(child)
        if node.get("type") in ("paragraph", "heading", "listItem", "tableRow", "callout"):
            chunks.append("\n")

    doc = payload.get("doc") if isinstance(payload, dict) else None
    if isinstance(doc, dict):
        walk(doc)
    return " ".join("".join(chunks).split())


def empty_doc() -> dict[str, Any]:
    return {"schema": 1, "doc": {"type": "doc", "content": [{"type": "paragraph"}]}}

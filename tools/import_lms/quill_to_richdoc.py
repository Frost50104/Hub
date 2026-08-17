"""Quill-HTML (выгрузка ServiceGuru) → RichDoc-ноды Hub.

Инструмент разовой миграции: запускается ЛОКАЛЬНО при сборке bundle, на VPS
не исполняется (там читается готовый manifest.json). Зависит от lxml.

Правила соответствия (whitelist Hub — app/services/rich_content.py):
    p → paragraph, br → hardBreak, ul/ol → bulletList/orderedList,
    li → listItem[paragraph], h3/h4 → heading(level 3/4),
    b/strong → bold, em/i → italic, u → underline, s/del → strike,
    a[href] → link (только https/mailto/tel — остальное теряет марку),
    span/b style="color: rgb(...)" → textStyle.color,
    class="ql-size-large" → textStyle.fontSize 20px.

Осознанно теряем: выравнивание (`ql-align-*` — attrs параграфа запрещены
валидатором), background-color, `color: currentcolor` (наследование),
`ql-cursor` (артефакт курсора редактора).
"""

from __future__ import annotations

import re
from typing import Any

from lxml import html as lxml_html

Node = dict[str, Any]

# Марки, которые несёт тег сам по себе.
_TAG_MARKS: dict[str, str] = {
    "b": "bold",
    "strong": "bold",
    "em": "italic",
    "i": "italic",
    "u": "underline",
    "s": "strike",
    "del": "strike",
    "strike": "strike",
}

_HEADING_TAGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 4, "h6": 4}

_RGB = re.compile(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)")
_SAFE_HREF = re.compile(r"^(https?://|mailto:|tel:)", re.IGNORECASE)
# Quill дублирует номер пункта в тексте: «1. Проведи осмотр…» внутри <ol>.
_LEADING_NUMBER = re.compile(r"^\s*\d{1,2}[.)]\s+")


def _color_from_style(style: str | None) -> str | None:
    """#rrggbb из `color: rgb(...)`/`color: #hex`; currentcolor → None."""
    if not style:
        return None
    for decl in style.split(";"):
        name, _, value = decl.partition(":")
        if name.strip().lower() != "color":
            continue
        value = value.strip().lower()
        if value in ("currentcolor", "inherit", "initial", "transparent", ""):
            return None
        if value.startswith("#") and re.fullmatch(r"#[0-9a-f]{3,8}", value):
            return value
        m = _RGB.match(value)
        if m:
            r, g, b = (min(255, int(x)) for x in m.groups())
            return f"#{r:02x}{g:02x}{b:02x}"
    return None


def _clean_text(text: str) -> str:
    """NBSP → пробел, схлопывание пробелов (Quill сыпет &nbsp; пачками)."""
    return re.sub(r"[ \t ]+", " ", text.replace(" ", " "))


def _marks_key(marks: list[Node]) -> str:
    return repr(sorted((m["type"], tuple(sorted(m.get("attrs", {}).items()))) for m in marks))


class _InlineCollector:
    """Собирает inline-содержимое элемента в список text/hardBreak-нод."""

    def __init__(self) -> None:
        self.out: list[Node] = []

    def add_text(self, text: str, marks: list[Node]) -> None:
        text = _clean_text(text)
        if not text:
            return
        # Склейка соседних text-нод с одинаковыми марками — меньше мусора.
        if self.out and self.out[-1].get("type") == "text":
            prev = self.out[-1]
            if _marks_key(prev.get("marks", [])) == _marks_key(marks):
                prev["text"] += text
                return
        node: Node = {"type": "text", "text": text}
        if marks:
            node["marks"] = marks
        self.out.append(node)

    def add_break(self) -> None:
        self.out.append({"type": "hardBreak"})

    def result(self) -> list[Node]:
        # Хвостовые/ведущие пробелы у краёв абзаца не нужны.
        nodes = list(self.out)
        while nodes and nodes[0].get("type") == "text" and not nodes[0]["text"].strip():
            nodes.pop(0)
        while nodes and nodes[-1].get("type") == "text" and not nodes[-1]["text"].strip():
            nodes.pop()
        if nodes:
            if nodes[0].get("type") == "text":
                nodes[0]["text"] = nodes[0]["text"].lstrip()
            if nodes[-1].get("type") == "text":
                nodes[-1]["text"] = nodes[-1]["text"].rstrip()
        return [n for n in nodes if n.get("type") != "text" or n["text"]]


def _element_marks(el, inherited: list[Node]) -> list[Node]:
    """Марки элемента поверх унаследованных (дедуп по типу)."""
    marks = list(inherited)
    seen = {m["type"] for m in marks}

    tag = el.tag if isinstance(el.tag, str) else ""
    mark_type = _TAG_MARKS.get(tag)
    if mark_type and mark_type not in seen:
        marks.append({"type": mark_type})
        seen.add(mark_type)

    if tag == "a":
        href = (el.get("href") or "").strip()
        if _SAFE_HREF.match(href) and len(href) <= 2000 and "link" not in seen:
            marks.append({"type": "link", "attrs": {"href": href}})
            seen.add("link")

    style_attrs: dict[str, str] = {}
    color = _color_from_style(el.get("style"))
    if color:
        style_attrs["color"] = color
    classes = (el.get("class") or "").split()
    if "ql-size-large" in classes:
        style_attrs["fontSize"] = "20px"
    elif "ql-size-huge" in classes:
        style_attrs["fontSize"] = "28px"
    elif "ql-size-small" in classes:
        style_attrs["fontSize"] = "12px"
    if style_attrs and "textStyle" not in seen:
        marks.append({"type": "textStyle", "attrs": style_attrs})

    return marks


def _collect_inline(el, collector: _InlineCollector, marks: list[Node]) -> None:
    if el.text:
        collector.add_text(el.text, marks)
    for child in el:
        tag = child.tag if isinstance(child.tag, str) else ""
        if tag == "br":
            collector.add_break()
        elif "ql-cursor" in (child.get("class") or "").split():
            pass  # артефакт редактора — выкидываем вместе с содержимым
        else:
            _collect_inline(child, collector, _element_marks(child, marks))
        if child.tail:
            collector.add_text(child.tail, marks)


def _paragraph_from(el, marks: list[Node] | None = None) -> Node:
    collector = _InlineCollector()
    _collect_inline(el, collector, marks or [])
    content = collector.result()
    # <p><br></p> — Quill-разделитель, а не перенос: пустой параграф.
    if all(n.get("type") == "hardBreak" for n in content):
        content = []
    node: Node = {"type": "paragraph"}
    if content:
        node["content"] = content
    return node


def _list_item(li, ordered: bool) -> Node:
    """listItem ВСЕГДА содержит paragraph — каноничная схема TipTap.

    Сервер контейнерную схему не проверяет, но редактор нормализует чужую
    структуру при первом открытии урока (и содержимое «прыгает»).
    """
    para = _paragraph_from(li)
    if ordered and para.get("content"):
        first = para["content"][0]
        if first.get("type") == "text":
            stripped = _LEADING_NUMBER.sub("", first["text"], count=1)
            if stripped != first["text"]:
                first["text"] = stripped
                if not stripped:
                    para["content"].pop(0)
    if not para.get("content"):
        para.pop("content", None)
    return {"type": "listItem", "content": [para]}


def _list_node(el) -> Node | None:
    """<ul>/<ol> → bulletList/orderedList. Quill 2 кодирует тип в li[data-list]."""
    items = el.findall("li")
    if not items:
        return None
    data_lists = {(li.get("data-list") or "").strip() for li in items}
    if "ordered" in data_lists:
        ordered = True
    elif "bullet" in data_lists:
        ordered = False
    else:
        ordered = el.tag == "ol"
    children = [_list_item(li, ordered) for li in items]
    return {"type": "orderedList" if ordered else "bulletList", "content": children}


def _block_nodes(el) -> list[Node]:
    tag = el.tag if isinstance(el.tag, str) else ""
    if tag in ("ul", "ol"):
        node = _list_node(el)
        return [node] if node else []
    if tag in _HEADING_TAGS:
        para = _paragraph_from(el)
        content = para.get("content")
        if not content:
            return []
        return [{"type": "heading", "attrs": {"level": _HEADING_TAGS[tag]}, "content": content}]
    if tag == "blockquote":
        inner = _paragraph_from(el)
        return [{"type": "blockquote", "content": [inner]}]
    if tag == "hr":
        return [{"type": "horizontalRule"}]
    if tag in ("div", "section", "article", "body"):
        out: list[Node] = []
        for child in el:
            out.extend(_block_nodes(child))
        return out
    # p и всё неизвестное — как параграф (текст не теряем).
    return [_paragraph_from(el)]


def quill_to_nodes(html_text: str) -> list[Node]:
    """HTML одной ячейки «Текст» → список блочных нод RichDoc."""
    if not html_text or not html_text.strip():
        return []
    fragment = lxml_html.fragment_fromstring(html_text, create_parent="div")
    nodes: list[Node] = []
    if fragment.text and fragment.text.strip():
        leading = _clean_text(fragment.text).strip()
        nodes.append({"type": "paragraph", "content": [{"type": "text", "text": leading}]})
    for child in fragment:
        nodes.extend(_block_nodes(child))

    # Схлопываем подряд идущие пустые параграфы (Quill сыпет <p><br></p>).
    def _is_empty(node: Node) -> bool:
        return node.get("type") == "paragraph" and not node.get("content")

    cleaned: list[Node] = []
    for node in nodes:
        if _is_empty(node) and (not cleaned or _is_empty(cleaned[-1])):
            continue
        cleaned.append(node)
    while cleaned and _is_empty(cleaned[-1]):
        cleaned.pop()
    while cleaned and _is_empty(cleaned[0]):
        cleaned.pop(0)
    return cleaned


def html_to_plain(html_text: str) -> str:
    """Плейнтекст (описания карточек ассортимента — обычный Text-столбец)."""
    if not html_text or not html_text.strip():
        return ""
    fragment = lxml_html.fragment_fromstring(html_text, create_parent="div")
    parts = [_clean_text(t) for t in fragment.itertext()]
    text = "".join(parts)
    return re.sub(r"\n{3,}", "\n\n", text).strip()

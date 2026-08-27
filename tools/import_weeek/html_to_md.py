"""HTML описаний WEEEK → GFM markdown. Только локально, зависит от lxml.

Зачем вообще конвертировать: Hub рендерит описание безопасным markdown-ом и
HTML НЕ интерпретирует (`web/src/components/Markdown.tsx`), поэтому сырой
`<p>Текст</p>` человек увидел бы буквально, вместе с тегами. Плюс
`tasks.search_vector` — GENERATED-колонка по title+description, и без чистки
поиск набрался бы токенами разметки.

Целевой рендер — react-markdown + remark-gfm, объявленные компоненты p, a,
ul/ol/li, h1–h3, table, code, blockquote. Всё, чего в этом списке нет,
приводим к тексту, а не выдумываем разметку.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from lxml import html as lxml_html

# Схемы, которые пускаем в ссылку. Тот же список, что у миграции LMS
# (`quill_to_richdoc._SAFE_HREF`): javascript:/data: в описании задачи не нужны.
_SAFE_HREF = re.compile(r"^(https?://|mailto:|tel:)", re.IGNORECASE)

_INLINE_WRAP: dict[str, str] = {
    "strong": "**", "b": "**",
    "em": "*", "i": "*",
    "del": "~~", "s": "~~", "strike": "~~",
    "code": "`",
}
# `u` намеренно НЕ здесь: подчёркивания в markdown нет, и любой суррогат
# (`<u>`, `__…__`) либо показался бы тегом, либо стал бы жирным.
_TRANSPARENT = frozenset({"u", "span", "font", "ins", "sub", "sup", "small", "abbr"})
_HEADINGS = {"h1": "#", "h2": "##", "h3": "###", "h4": "###", "h5": "###", "h6": "###"}

_ESCAPE = re.compile(r"([\\`*_\[\]<>])")
_LINE_START = re.compile(r"^(\s*)([#>+-])(\s)", re.MULTILINE)
# «1. пункт» в начале строки — нумерованный список. Экранируем ТОЧКУ:
# `\1.` не является escape-последовательностью CommonMark, и слэш остался бы
# виден человеку, а `1\.` рендерится как «1.».
_LINE_START_NUM = re.compile(r"^(\s*)(\d{1,9})([.)])(\s)", re.MULTILINE)


def _escape(text: str) -> str:
    """Экранировать то, что иначе станет разметкой.

    «сумма 3*5*7» без этого превращается в курсив, «- 5%» в начале строки —
    в маркер списка, а «пункт 1. Проверить» — в нумерованный список.
    """
    out = _ESCAPE.sub(r"\\\1", text)
    out = _LINE_START.sub(r"\1\\\2\3", out)
    return _LINE_START_NUM.sub(r"\1\2\\\3\4", out)


def _clean(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"[ \t\r\f\v\u00a0]+", " ", text.replace("\u00a0", " "))


class _Converter:
    def __init__(self, images: Mapping[str, str] | None) -> None:
        self._images = images or {}
        self.notes: list[str] = []

    # ─── inline ─────────────────────────────────────────────────────────────

    def inline(self, el) -> str:  # noqa: ANN001 — lxml element
        """Инлайн-содержимое узла.

        Блочные дети ПРОПУСКАЮТСЯ (их разберёт `blocks`/`_list`), но их хвост
        забираем: `<li>два<ul>…</ul> ещё</li>` — «ещё» принадлежит пункту.
        Без этого вложенный список приезжал и в строку родителя, и отдельно.
        """
        parts: list[str] = []
        for child in el:
            if not _is_block(child):
                parts.append(self._inline_node(child))
            parts.append(_escape(_clean(child.tail)))
        return "".join(parts)

    def _inline_node(self, el) -> str:  # noqa: ANN001
        tag = str(el.tag).lower() if isinstance(el.tag, str) else ""
        if tag == "br":
            return "  \n"
        if tag == "img":
            return self._image(el)
        if tag == "a":
            return self._link(el)
        inner = _escape(_clean(el.text)) + self.inline(el)
        if tag in _INLINE_WRAP:
            stripped = inner.strip()
            if not stripped:
                return inner
            wrap = _INLINE_WRAP[tag]
            return f"{wrap}{stripped}{wrap}"
        if tag in _TRANSPARENT or not tag:
            return inner
        # Незнакомый инлайн-тег (их в выгрузке не встретилось) — отдаём текст.
        return inner

    def _link(self, el) -> str:  # noqa: ANN001
        href = (el.get("href") or "").strip()
        text = (_escape(_clean(el.text)) + self.inline(el)).strip()
        if not _SAFE_HREF.match(href):
            self.notes.append(f"ссылка со схемой вне белого списка: {href[:60]}")
            return text or _escape(href)
        # Скобки внутри URL ломают markdown-ссылку.
        safe = href.replace("(", "%28").replace(")", "%29")
        if not text or text == _escape(href):
            return f"<{safe}>" if " " not in safe else safe
        return f"[{text}]({safe})"

    def _image(self, el) -> str:  # noqa: ANN001
        src = (el.get("src") or "").strip()
        name = self._images.get(src)
        if name:
            # Файл уехал во вложения задачи — голый ![](url) отрисовался бы
            # битой картинкой, ссылки WEEEK умрут вместе с подпиской.
            return f"Изображение: {_escape(name)} — во вложениях"
        self.notes.append(f"картинка не перенесена: {src[:80]}")
        return "\\[изображение из WEEEK не перенесено\\]"

    # ─── blocks ─────────────────────────────────────────────────────────────

    def blocks(self, el) -> list[str]:  # noqa: ANN001
        """Содержимое узла как список markdown-блоков, В ПОРЯДКЕ ДОКУМЕНТА.

        Инлайн-куски копятся в буфер и сбрасываются на границе блочного
        ребёнка: `<div>текст<p>абзац</p>хвост</div>` обязан дать три блока
        подряд, а не склеить «текстхвост» и приписать абзац после.
        """
        out: list[str] = []
        buffer: list[str] = []

        def flush() -> None:
            text = "".join(buffer).strip()
            buffer.clear()
            if text:
                out.append(text)

        buffer.append(_escape(_clean(el.text)))
        for child in el:
            if _is_block(child):
                flush()
                out.extend(self._block_node(child))
            else:
                buffer.append(self._inline_node(child))
            buffer.append(_escape(_clean(child.tail)))
        flush()
        return out

    def _block_node(self, el) -> list[str]:  # noqa: ANN001
        tag = str(el.tag).lower() if isinstance(el.tag, str) else ""
        if tag in _HEADINGS:
            text = (_escape(_clean(el.text)) + self.inline(el)).strip()
            return [f"{_HEADINGS[tag]} {text}"] if text else []
        if tag == "hr":
            return ["---"]
        if tag in ("ul", "ol"):
            return self._list(el, ordered=tag == "ol", depth=0)
        if tag == "table":
            return self._table(el)
        if tag == "blockquote":
            inner = self.blocks(el)
            if not inner:
                return []
            quoted = [f"> {line}" for b in inner for line in b.split("\n")]
            return ["\n".join(quoted)]
        if tag in ("pre",):
            text = el.text_content().strip("\n")
            return [f"```\n{text}\n```"] if text.strip() else []
        if tag in ("div", "section", "article", "p") or tag in _TRANSPARENT:
            return self.blocks(el)
        text = (_escape(_clean(el.text)) + self.inline(el)).strip()
        return [text] if text else []

    def _list(self, el, *, ordered: bool, depth: int) -> list[str]:  # noqa: ANN001
        lines: list[str] = []
        index = 0
        for li in el:
            if str(li.tag).lower() != "li":
                continue
            index += 1
            marker = f"{index}. " if ordered else "- "
            body = (_escape(_clean(li.text)) + self.inline(li)).strip()
            pad = "  " * depth
            lines.append(f"{pad}{marker}{body}" if body else f"{pad}{marker}")
            for child in li:
                if str(child.tag).lower() in ("ul", "ol"):
                    lines.extend(self._list(child, ordered=str(child.tag).lower() == "ol",
                                            depth=depth + 1))
        return ["\n".join(lines)] if lines else []

    def _table(self, el) -> list[str]:  # noqa: ANN001
        """GFM-таблица. Ячейка не умеет переносов — склеиваем через « / »."""
        rows: list[list[str]] = []
        for tr in el.iter("tr"):
            cells = [self._cell(td) for td in tr if str(td.tag).lower() in ("td", "th")]
            if cells:
                rows.append(cells)
        if not rows or not any(cell for row in rows for cell in row):
            # Вёрстка ради вёрстки: пустая сетка в markdown выглядит поломкой.
            return []
        width = max(len(r) for r in rows)
        rows = [r + [""] * (width - len(r)) for r in rows]
        has_head = any(str(td.tag).lower() == "th" for tr in el.iter("tr") for td in tr)
        head = rows[0] if has_head else [""] * width
        body = rows[1:] if has_head else rows
        lines = [
            "| " + " | ".join(head) + " |",
            "| " + " | ".join(["---"] * width) + " |",
            *("| " + " | ".join(r) + " |" for r in body),
        ]
        return ["\n".join(lines)]

    def _cell(self, td) -> str:  # noqa: ANN001
        text = (_escape(_clean(td.text)) + self.inline(td)).strip()
        return text.replace("|", "\\|").replace("\n", " / ").strip()


def _is_block(el) -> bool:  # noqa: ANN001
    tag = str(el.tag).lower() if isinstance(el.tag, str) else ""
    return tag in {"p", "div", "ul", "ol", "table", "blockquote", "pre", "hr", "section",
                   "article", *_HEADINGS}


def html_to_md(
    raw: str | None, *, images: Mapping[str, str] | None = None, limit: int = 18_000
) -> tuple[str | None, list[str]]:
    """→ (markdown или None, замечания для отчёта сборки).

    `images`: src → имя файла, который сборщик успел скачать и приложит к
    задаче. `limit` с запасом ниже 20 000 из `TaskCreate.description`: сверху
    джоба ещё допишет блок «перенесено из WEEEK».
    """
    if not raw or not raw.strip():
        return None, []
    fragment = lxml_html.fragment_fromstring(raw, create_parent="div")
    conv = _Converter(images)
    blocks = [b for b in conv.blocks(fragment) if b.strip()]
    text = "\n\n".join(blocks).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    if not text:
        return None, conv.notes
    if len(text) > limit:
        cut = text.rfind("\n\n", 0, limit)
        text = (text[:cut] if cut > limit // 2 else text[:limit]).rstrip()
        text += "\n\n_… описание обрезано при переносе из WEEEK_"
        conv.notes.append("описание обрезано по длине")
    return text, conv.notes

"""HTML описаний WEEEK → markdown, который Hub действительно умеет показать.

Целевой рендер — `web/src/components/Markdown.tsx`: react-markdown + GFM,
HTML НЕ интерпретируется. Поэтому каждый кейс здесь проверяет одно из двух:
разметка доехала правильно либо честно превратилась в текст. Промежуточного
варианта «покажем тег буквально» быть не должно.
"""

from __future__ import annotations

from tools.import_weeek.html_to_md import html_to_md


def md(raw: str, **kw) -> str:
    text, _notes = html_to_md(raw, **kw)
    return text or ""


class TestInline:
    def test_bold_italic_strike(self):
        assert md("<p><b>ж</b> <em>к</em> <del>з</del></p>") == "**ж** *к* ~~з~~"

    def test_underline_becomes_plain_text(self):
        # Подчёркивания в markdown нет: `<u>` показался бы тегом, а `__…__`
        # отрисовался бы жирным — оба варианта врут.
        assert md("<p><u>важно</u></p>") == "важно"

    def test_br_is_a_hard_break(self):
        assert md("<p>до<br>после</p>") == "до  \nпосле"

    def test_span_is_transparent(self):
        assert md('<p><span style="color:red">цвет</span></p>') == "цвет"

    def test_empty_html_is_none(self):
        assert html_to_md("<p></p>") == (None, [])
        assert html_to_md(None) == (None, [])
        assert html_to_md("   ") == (None, [])


class TestLinks:
    def test_safe_schemes(self):
        assert md('<p><a href="https://a.ru/x">тут</a></p>') == "[тут](https://a.ru/x)"
        assert md('<p><a href="mailto:a@b.ru">почта</a></p>') == "[почта](mailto:a@b.ru)"

    def test_unsafe_scheme_degrades_to_text(self):
        text, notes = html_to_md('<p><a href="javascript:alert(1)">клик</a></p>')
        assert text == "клик"
        assert notes and "белого списка" in notes[0]

    def test_parentheses_in_url_are_encoded(self):
        # Скобка внутри url обрывает markdown-ссылку на первой же «)».
        assert md('<p><a href="https://a.ru/x(1)">т</a></p>') == "[т](https://a.ru/x%281%29)"

    def test_weeek_link_is_kept(self):
        # Пока подписка жива, короткие ссылки рабочие — обрывать их нечестно.
        assert "weeek.link" in md('<p><a href="https://weeek.link/0eZ">т</a></p>')


class TestBlocks:
    def test_paragraphs_separated_by_blank_line(self):
        assert md("<p>раз</p><p>два</p>") == "раз\n\nдва"

    def test_headings_collapse_to_three_levels(self):
        assert md("<h1>а</h1>") == "# а"
        assert md("<h5>д</h5>") == "### д"  # компонентов ниже h3 в Hub нет

    def test_hr(self):
        assert md("<p>а</p><hr><p>б</p>") == "а\n\n---\n\nб"

    def test_nested_list_is_not_duplicated(self):
        # Текст вложенного списка приезжал и в строку родителя, и отдельно.
        assert md("<ul><li>раз</li><li>два<ul><li>вложено</li></ul> ещё</li></ul>") == (
            "- раз\n- два ещё\n  - вложено"
        )

    def test_ordered_list_numbering(self):
        assert md("<ol><li>а</li><li>б</li></ol>") == "1. а\n2. б"

    def test_mixed_container_keeps_document_order(self):
        assert md("<div>текст<p>абзац</p>хвост</div>") == "текст\n\nабзац\n\nхвост"

    def test_blockquote(self):
        assert md("<blockquote><p>цитата</p></blockquote>") == "> цитата"


class TestTables:
    def test_table_with_header(self):
        raw = "<table><tr><th>А</th><th>Б</th></tr><tr><td>1</td><td>2</td></tr></table>"
        assert md(raw) == "| А | Б |\n| --- | --- |\n| 1 | 2 |"

    def test_table_without_header_gets_an_empty_one(self):
        # GFM без строки-шапки таблицу не распознаёт вовсе.
        raw = "<table><tr><td>без</td><td>шапки</td></tr></table>"
        assert md(raw) == "|  |  |\n| --- | --- |\n| без | шапки |"

    def test_pipe_inside_cell_is_escaped(self):
        raw = "<table><tr><th>А</th></tr><tr><td>2|3</td></tr></table>"
        assert "2\\|3" in md(raw)

    def test_table_of_empty_cells_is_dropped(self):
        # Вёрстка ради вёрстки: пустая сетка в markdown выглядит поломкой.
        assert md("<table><tr><td></td></tr><tr><td> </td></tr></table>") == ""

    def test_ragged_rows_are_padded(self):
        raw = "<table><tr><th>А</th><th>Б</th></tr><tr><td>1</td></tr></table>"
        assert md(raw).splitlines()[-1] == "| 1 |  |"


class TestEscaping:
    def test_emphasis_characters(self):
        assert md("<p>сумма 3*5 и _подчерк_</p>") == "сумма 3\\*5 и \\_подчерк\\_"

    def test_line_start_markers(self):
        assert md("<p>- 5% скидка</p>") == "\\- 5% скидка"
        assert md("<p># решётка</p>") == "\\# решётка"

    def test_numbered_line_escapes_the_dot_not_the_digit(self):
        # `\1.` не escape-последовательность CommonMark — слэш остался бы виден.
        assert md("<p>1. пункт</p>") == "1\\. пункт"

    def test_angle_brackets(self):
        assert md("<p>&lt;не тег&gt;</p>") == "\\<не тег\\>"


class TestImages:
    def test_downloaded_image_points_at_attachment(self):
        raw = '<p><img src="https://api.weeek.net/x.png"></p>'
        assert md(raw, images={"https://api.weeek.net/x.png": "shot.png"}) == (
            "Изображение: shot.png — во вложениях"
        )

    def test_missing_image_is_honest_text(self):
        # Голый ![](url) отрисовался бы битой картинкой: подписанные ссылки
        # WEEEK умрут вместе с подпиской.
        text, notes = html_to_md('<p><img src="https://api.weeek.net/x.png"></p>')
        assert text == "\\[изображение из WEEEK не перенесено\\]"
        assert notes and "картинка не перенесена" in notes[0]


class TestLimit:
    def test_long_text_is_cut_on_paragraph_boundary(self):
        raw = "".join(f"<p>{'я' * 90}</p>" for _ in range(40))
        text, notes = html_to_md(raw, limit=1000)
        assert len(text) < 1200
        assert text.endswith("_… описание обрезано при переносе из WEEEK_")
        assert "обрезано по длине" in notes[-1]

    def test_short_text_is_untouched(self):
        text, notes = html_to_md("<p>коротко</p>", limit=1000)
        assert text == "коротко"
        assert notes == []

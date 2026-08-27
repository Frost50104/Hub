"""Кастом-поля и вложения при сборке bundle.

Кастом-поля — единственное место сборщика, где «пусто» неочевидно: в WEEEK
снятая галочка приходит как `false` и от «поля не трогали» ничем не отличается.
"""

from __future__ import annotations

from tools.import_weeek.build_bundle import (
    CF_TYPE,
    EXT_MIME,
    Report,
    _custom_field_specs,
    _custom_values,
    _inline_image_ids,
    _is_blank,
    _option_id,
    _sniff_mime,
)

PEOPLE = {"u-1": {"email": "a@t.ru", "name": "Иван Иванов"},
          "u-2": {"email": "b@t.ru", "name": "Пётр Петров"}}


def _task(**fields) -> dict:
    return {"id": 1, "customFields": list(fields.get("cf", []))}


class TestBlank:
    def test_false_counts_as_empty(self):
        # Иначе «Компенсация» (одно поле бухгалтерии) завела бы определение
        # во всех 47 проектах и значение у каждой из 16 703 задач.
        assert _is_blank(False) is True

    def test_zero_and_empty_string_are_kept_apart(self):
        assert _is_blank("") is True
        assert _is_blank([]) is True
        assert _is_blank(None) is True
        assert _is_blank(True) is False
        assert _is_blank("0") is False


class TestDefinitions:
    def test_only_fields_with_values_get_a_definition(self):
        tasks = [
            _task(cf=[
                {"id": "cf-1", "name": "Контрагент", "type": "text", "value": "ООО"},
                {"id": "cf-2", "name": "Компенсация", "type": "boolean", "value": False},
            ])
        ]
        specs = _custom_field_specs(tasks, Report())
        assert [s["name"] for s in specs] == ["Контрагент"]

    def test_unnamed_definitions_are_skipped(self):
        # В Hub имя поля обязательно, а WEEEK держит безымянные определения
        # с единичными значениями.
        report = Report()
        specs = _custom_field_specs(
            [_task(cf=[{"id": "x", "name": None, "type": "text", "value": "v"}])], report
        )
        assert specs == []
        assert report.counters["кастом-поле без имени пропущено"] == 1

    def test_option_ids_fit_the_hub_schema(self):
        """`CustomFieldOption.id` — max_length=32, а в WEEEK это UUID из 36.

        В JSONB ограничения нет, поэтому длинный id записался бы молча, а
        `GET /projects/{id}/custom-fields` после этого отдавал бы 500 на весь
        проект — поймано репетицией на staging 25.08.
        """
        specs = _custom_field_specs(
            [_task(cf=[{
                "id": "cf-3", "name": "Статья", "type": "select",
                "value": "9df70d73-176b-4e57-9770-354fd4e1d167",
                "options": [{"id": "9df70d73-176b-4e57-9770-354fd4e1d167",
                             "name": "Аренда", "color": None}],
            }])],
            Report(),
        )
        assert all(len(o["id"]) <= 32 for o in specs[0]["options"])

    def test_option_id_is_deterministic_and_short(self):
        raw = "9df70d73-176b-4e57-9770-354fd4e1d167"
        assert _option_id(raw) == "9df70d73176b4e579770354fd4e1d167"
        assert _option_id(raw) == _option_id(raw)
        assert len(_option_id("x" * 40)) == 32
        assert _option_id("короткий") == "короткий"

    def test_select_carries_its_options(self):
        specs = _custom_field_specs(
            [_task(cf=[{
                "id": "cf-3", "name": "Статья", "type": "select", "value": "o-1",
                "options": [{"id": "o-1", "name": "Аренда", "color": "#fff"}],
            }])],
            Report(),
        )
        assert specs[0]["type"] == "select"
        assert specs[0]["options"] == [{"id": "o-1", "label": "Аренда", "color": "#fff"}]

    def test_every_weeek_type_we_saw_is_mapped(self):
        assert set(CF_TYPE) >= {"text", "select", "boolean", "member"}
        # `member` → text с ФИО: `person` требует employee_id, а он есть у
        # пятерых из 41 — 96% значений просто пропали бы.
        assert CF_TYPE["member"] == "text"


class TestValues:
    def _specs(self, raw: list[dict]) -> tuple[dict, list[dict]]:
        specs = _custom_field_specs([_task(cf=raw)], Report())
        return {s["weeek_id"]: s for s in specs}, raw

    def test_member_becomes_a_readable_name(self):
        raw = [{"id": "cf-4", "name": "Инициатор", "type": "member", "value": ["u-1", "u-2"]}]
        by_id, _ = self._specs(raw)
        values = _custom_values(_task(cf=raw), by_id, PEOPLE, Report())
        assert values == [{"field": "cf-4", "value": "Иван Иванов, Пётр Петров"}]

    def test_select_value_survives_validation(self):
        raw = [{"id": "cf-3", "name": "Статья", "type": "select", "value": "o-1",
                "options": [{"id": "o-1", "name": "Аренда", "color": None}]}]
        by_id, _ = self._specs(raw)
        assert _custom_values(_task(cf=raw), by_id, PEOPLE, Report()) == [
            {"field": "cf-3", "value": "o-1"}
        ]

    def test_select_value_is_shortened_together_with_its_option(self):
        # Значение и опция обязаны схлопываться ОДИНАКОВО, иначе валидатор
        # скажет «опция не существует» и значение потеряется.
        uuid = "9df70d73-176b-4e57-9770-354fd4e1d167"
        raw = [{"id": "cf-3", "name": "Статья", "type": "select", "value": uuid,
                "options": [{"id": uuid, "name": "Аренда", "color": None}]}]
        by_id, _ = self._specs(raw)
        assert _custom_values(_task(cf=raw), by_id, PEOPLE, Report()) == [
            {"field": "cf-3", "value": "9df70d73176b4e579770354fd4e1d167"}
        ]

    def test_value_failing_validation_is_reported_not_raised(self):
        # 422 на проде уронил бы чанк на 500 задач — ловим здесь.
        raw = [{"id": "cf-3", "name": "Статья", "type": "select", "value": "нет-такой",
                "options": [{"id": "o-1", "name": "Аренда", "color": None}]}]
        by_id, _ = self._specs(raw)
        report = Report()
        assert _custom_values(_task(cf=raw), by_id, PEOPLE, report) == []
        assert report.notes and "не существует" in report.notes[0]

    def test_true_checkbox_is_kept(self):
        raw = [{"id": "cf-2", "name": "Компенсация", "type": "boolean", "value": True}]
        by_id, _ = self._specs(raw)
        assert _custom_values(_task(cf=raw), by_id, PEOPLE, Report()) == [
            {"field": "cf-2", "value": True}
        ]


class TestInlineImages:
    def test_ids_are_extracted_from_src(self):
        html = '<p><img src="https://api.weeek.net/ws/1/files/abc-1"> и <img src="x/def-2?q=1">'
        assert _inline_image_ids(html) == {"abc-1", "def-2"}

    def test_no_images(self):
        assert _inline_image_ids("<p>текст</p>") == set()
        assert _inline_image_ids(None) == set()


class TestMime:
    def test_whitelist_mirrors_hub(self):
        from app.services.attachments import ALLOWED_MIME

        # Расширять белый список ради переноса нельзя: это защитный инвариант
        # с парным зеркалом на фронте.
        assert set(EXT_MIME.values()) <= ALLOWED_MIME


class TestSniffMime:
    """Расширение врёт чаще, чем кажется.

    В выгрузке нашлись «IMG_7866.HEIC» (внутри JPEG), «Season menu.png»
    (WebP) и «…jpg» (PNG). Hub такие файлы отвергает `sniff_mismatch`, так
    что MIME определяем по содержимому.
    """

    def test_extension_lies_and_content_wins(self):
        assert _sniff_mime(b"\xff\xd8\xff\xe0\x00\x10JFIF", "image/heic") == "image/jpeg"
        assert _sniff_mime(b"RIFFJ\xad\x00\x00WEBPVP8 ", "image/png") == "image/webp"
        assert _sniff_mime(b"\x89PNG\r\n\x1a\n\x00", "image/jpeg") == "image/png"

    def test_pdf_with_junk_before_header(self):
        assert _sniff_mime(b"\xef\xbb\xbf\n%PDF-1.4", "application/pdf") == "application/pdf"

    def test_families_without_a_signature_keep_the_extension(self):
        # zip/OLE/текст по сигнатуре друг от друга не отличить.
        xlsx = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        assert _sniff_mime(b"PK\x03\x04rest", xlsx) == xlsx
        assert _sniff_mime(b"a;b;c", "text/csv") == "text/csv"

    def test_heic_brand_trusts_a_heic_extension(self):
        assert _sniff_mime(b"\x00\x00\x00\x18ftypheic", "image/heic") == "image/heic"
        # ftyp при чужом расширении — всё равно HEIC, а не то, что заявлено.
        assert _sniff_mime(b"\x00\x00\x00\x18ftypheic", "image/png") == "image/heic"

    def test_result_is_always_allowed_by_hub(self):
        from app.services.attachments import ALLOWED_MIME

        for head in (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"GIF89a",
                     b"RIFF\x00\x00\x00\x00WEBP", b"%PDF-1.7"):
            assert _sniff_mime(head, "image/png") in ALLOWED_MIME

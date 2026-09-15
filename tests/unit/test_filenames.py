"""Имя файла: отдельно для хранилища и отдельно для человека.

ОС 14.09: материал библиотеки скачивался как «xlsx.xlsx», а у части людей —
как «xlsx» без расширения, и Windows такой файл не открывал. Причина не в
импорте из WEEEK, как считалось: `_sanitize_filename` выбрасывает всё
не-ASCII, поэтому «ЛДМО.xlsx» превращалось в «xlsx» — и это же продолжало
происходить с каждой новой загрузкой кириллического имени.
"""

from __future__ import annotations

from app.services.attachments import (
    _sanitize_filename,
    content_disposition,
    display_filename,
    download_filename,
)

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class TestSanitizeStillAsciiOnly:
    def test_кириллица_в_пути_по_прежнему_срезается(self):
        # Это НЕ баг: `storage_key` обязан быть ASCII. Баг был в том, что это
        # же значение уезжало в колонку с именем файла.
        assert _sanitize_filename("ЛДМО.xlsx") == "xlsx"


class TestDisplayFilename:
    def test_кириллица_сохраняется(self):
        assert display_filename("ЛДМО.xlsx") == "ЛДМО.xlsx"
        assert display_filename("Бланк заказа.docx") == "Бланк заказа.docx"

    def test_путь_отбрасывается(self):
        assert display_filename("../../etc/passwd") == "passwd"
        assert display_filename(r"C:\\Users\\Петя\\отчёт.pdf") == "отчёт.pdf"

    def test_запрещённые_символы_windows_вычищены(self):
        assert display_filename('отчёт*?.pdf') == "отчёт.pdf"
        assert display_filename('а:б|в.txt') == "а б в.txt"

    def test_хвостовые_точки_и_пробелы_срезаны(self):
        # Windows их не сохраняет — лучше срезать самим, чем получить сюрприз.
        assert display_filename("имя. ") == "имя"

    def test_пустое_имя_не_роняет(self):
        assert display_filename("") == "file"
        assert display_filename("   ") == "file"


class TestDownloadFilename:
    def test_нормальное_имя_отдаётся_как_есть(self):
        assert download_filename("заказ.xlsx", mime=XLSX, fallback="ЛДМО") == "заказ.xlsx"

    def test_голое_расширение_чинится_названием(self):
        # Ровно случай из ОС: в колонке «xlsx», материал называется «ЛДМО».
        assert download_filename("xlsx", mime=XLSX, fallback="ЛДМО") == "ЛДМО.xlsx"

    def test_незнакомый_mime_берёт_расширение_из_испорченной_строки(self):
        assert (
            download_filename("docx", mime="application/x-unknown", fallback="Бланк")
            == "Бланк.docx"
        )

    def test_имени_нет_вовсе(self):
        assert download_filename(None, mime=XLSX, fallback="ЛДМО") == "ЛДМО.xlsx"
        assert download_filename("", mime=XLSX, fallback="ЛДМО") == "ЛДМО.xlsx"

    def test_скрытое_имя_с_точки_не_считается_именем(self):
        assert download_filename(".xlsx", mime=XLSX, fallback="ЛДМО") == "ЛДМО.xlsx"

    def test_ни_mime_ни_расширения_имя_без_расширения(self):
        assert (
            download_filename("", mime="application/x-unknown", fallback="Бланк")
            == "Бланк"
        )

    def test_вложение_без_названия_задачи(self):
        # У вложений осмысленного названия нет — фолбэк общий.
        assert (
            download_filename("docx", mime=None, fallback="вложение") == "вложение.docx"
        )


class TestContentDisposition:
    """Заголовок, который собираем РУКАМИ (X-Accel медиа, CSV-экспорты).

    Кириллица, вписанная в `filename="…"`, роняет ответ: заголовки HTTP
    кодируются latin-1. До 14.09 на этом молча падал в 500 экспорт
    результатов опроса — все три опроса на проде названы по-русски.
    """

    def test_ascii_остаётся_простым(self):
        assert (
            content_disposition("report.csv", disposition_type="attachment")
            == 'attachment; filename="report.csv"'
        )

    def test_кириллица_уходит_в_rfc_5987(self):
        out = content_disposition("ЛДМО.xlsx")
        assert out.startswith("inline; filename*=utf-8''")
        assert "%D0%9B" in out

    def test_кавычка_не_рвёт_заголовок(self):
        assert '"' not in content_disposition('a"b.csv', disposition_type="attachment")

    def test_заголовок_кодируется_в_latin1(self):
        # Тот самый предохранитель: результат обязан пережить сборку ответа.
        content_disposition("Опрос-results.csv").encode("latin-1")

"""resolve_mime — восстановление MIME из расширения ТОЛЬКО для .heic/.heif.

Десктопные браузеры шлют HEIC как application/octet-stream или без типа;
общий mimetypes.guess_type запрещён — он «спас» бы и опасные типы
(octet-stream + .svg → image/svg+xml), ломая fail-closed whitelist.
"""

from __future__ import annotations

from uuid import uuid4

from app.services.attachments import ALLOWED_MIME, resolve_mime, storage_key_for


def test_octet_stream_heic_recovers():
    assert resolve_mime("application/octet-stream", "IMG_0001.HEIC") == "image/heic"


def test_empty_type_heif_recovers():
    assert resolve_mime(None, "photo.heif") == "image/heif"
    assert resolve_mime("", "photo.heif") == "image/heif"


def test_octet_stream_exe_stays_generic():
    # .exe не в маппинге — остаётся octet-stream → 415 на эндпоинте.
    assert resolve_mime("application/octet-stream", "setup.exe") == (
        "application/octet-stream"
    )
    assert "application/octet-stream" not in ALLOWED_MIME


def test_octet_stream_svg_not_rescued():
    # Ключевой fail-closed кейс: generic-тип + .svg НЕ превращается в image/svg+xml.
    assert resolve_mime("application/octet-stream", "logo.svg") == (
        "application/octet-stream"
    )
    assert "image/svg+xml" not in ALLOWED_MIME


def test_charset_parameter_stripped():
    assert resolve_mime("image/jpeg; charset=binary", "a.jpg") == "image/jpeg"


def test_declared_type_wins_over_extension():
    # Явно заявленный тип не переопределяется расширением.
    assert resolve_mime("image/png", "weird.heic") == "image/png"


def test_heic_family_allowed():
    for mime in ("image/heic", "image/heif", "image/heic-sequence", "image/heif-sequence"):
        assert mime in ALLOWED_MIME


# ─── sniff_mismatch — магические байты против заявленного MIME (QA-0821 #11) ──

from app.services.attachments import sniff_mismatch  # noqa: E402

_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 8


def test_sniff_real_signatures_pass():
    assert sniff_mismatch("image/png", _PNG) is False
    assert sniff_mismatch("image/jpeg", b"\xff\xd8\xff\xe0\x00\x10JFIF") is False
    assert sniff_mismatch("image/gif", b"GIF89a\x01\x00") is False
    assert sniff_mismatch("image/webp", b"RIFF\x24\x00\x00\x00WEBPVP8 ") is False
    assert sniff_mismatch("application/pdf", b"%PDF-1.7\n%\xe2\xe3") is False
    assert sniff_mismatch("application/zip", b"PK\x03\x04\x14\x00") is False
    assert sniff_mismatch("application/zip", b"PK\x05\x06" + b"\x00" * 18) is False  # пустой
    assert sniff_mismatch(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        b"PK\x03\x04\x14\x00\x06\x00",
    ) is False
    assert sniff_mismatch("application/msword", _OLE) is False
    assert sniff_mismatch("image/heic", b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00") is False
    assert sniff_mismatch("image/heif", b"\x00\x00\x00\x1cftypmif1") is False
    # Видео: mp4/mov — тот же ISO-BMFF, что и HEIC; webm — EBML.
    assert sniff_mismatch("video/mp4", b"\x00\x00\x00\x20ftypisom\x00\x00\x02\x00") is False
    assert sniff_mismatch("video/quicktime", b"\x00\x00\x00\x14ftypqt  ") is False
    assert sniff_mismatch("video/webm", b"\x1a\x45\xdf\xa3\x01\x00\x00\x00") is False


def test_sniff_renamed_executable_is_rejected():
    mz = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff\x00\x00"
    assert sniff_mismatch("image/png", mz) is True
    assert sniff_mismatch("image/jpeg", mz) is True
    assert sniff_mismatch("application/pdf", mz) is True
    assert sniff_mismatch("application/zip", mz) is True
    assert sniff_mismatch("application/msword", mz) is True
    assert sniff_mismatch("image/heic", mz) is True
    assert sniff_mismatch("image/webp", b"RIFF\x00\x00\x00\x00AVI LIST") is True
    # Ключевой кейс видео: whitelist обходится переименованием, поэтому
    # заявленный video/* обязан подтверждаться сигнатурой.
    assert sniff_mismatch("video/mp4", mz) is True
    assert sniff_mismatch("video/quicktime", mz) is True
    assert sniff_mismatch("video/webm", mz) is True
    # AVI — тоже RIFF, но не WebM: EBML-заголовка в нём нет.
    assert sniff_mismatch("video/webm", b"RIFF\x00\x00\x00\x00AVI LIST") is True


def test_sniff_pdf_with_junk_before_header_passes():
    assert sniff_mismatch("application/pdf", b"\xef\xbb\xbf\n\n%PDF-1.4") is False


def test_sniff_skips_text_and_unknown_types():
    # Текстовые форматы сигнатуры не имеют (UTF-16/BOM легальны).
    assert sniff_mismatch("text/plain", b"\xff\xfeh\x00i\x00") is False
    assert sniff_mismatch("text/csv", b"a;b;c") is False
    assert sniff_mismatch("application/json", b"{}") is False
    assert sniff_mismatch("application/x-unknown", b"MZ") is False
    # Пустой файл — решает whitelist, не сниффер.
    assert sniff_mismatch("image/png", b"") is False


def test_octet_stream_video_recovers():
    """Главная причина, по которой видео не грузилось бы и после правки.

    Файловые менеджеры Android и часть десктопных браузеров отдают видео как
    `application/octet-stream` — ровно та же история, из-за которой в карте
    появились `.heic/.heif`. Без восстановления человек снова получил бы 415.
    """
    assert resolve_mime("application/octet-stream", "VID_20260915.mp4") == "video/mp4"
    assert resolve_mime(None, "IMG_0042.MOV") == "video/quicktime"
    assert resolve_mime("", "screen.webm") == "video/webm"
    for mime in ("video/mp4", "video/quicktime", "video/webm"):
        assert mime in ALLOWED_MIME


def test_recovered_video_still_faces_the_sniffer():
    """Почему восстанавливать видео можно, а SVG — нельзя.

    Карта расширений сама по себе whitelist не обходит: следом идёт сниффер, и
    у всех трёх контейнеров есть однозначная сигнатура. У SVG её нет — поэтому
    его в карте нет и быть не должно (см. test_octet_stream_svg_not_rescued).
    """
    mime = resolve_mime("application/octet-stream", "fake.mp4")
    assert sniff_mismatch(mime, b"MZ\x90\x00\x03\x00\x00\x00") is True


class TestSizeLimit:
    """Потолок зависит от вида файла: 20 МБ документам, гигабайт видео."""

    def test_video_gets_its_own_ceiling(self):
        from app.services.attachments import attachment_size_limit

        assert attachment_size_limit("video/mp4") == 1024 * 1024 * 1024
        assert attachment_size_limit("video/quicktime") == 1024 * 1024 * 1024
        assert attachment_size_limit("video/webm") == 1024 * 1024 * 1024

    def test_documents_keep_twenty_megabytes(self):
        from app.services.attachments import attachment_size_limit

        assert attachment_size_limit("application/pdf") == 20 * 1024 * 1024
        assert attachment_size_limit("image/png") == 20 * 1024 * 1024
        assert attachment_size_limit("text/plain") == 20 * 1024 * 1024


class TestStorageKey:
    """`unique=` — детерминированный путь для разового импорта.

    Осиротевший файл в Hub удалить некому (`unlink` есть только в ручке
    удаления вложения, sweeper'а нет), поэтому повторный прогон импорта
    обязан писать в ТОТ ЖЕ путь, а не плодить копии.
    """

    def test_default_is_random(self):
        tenant, task = uuid4(), uuid4()
        first, _ = storage_key_for(tenant, task, "отчёт.pdf")
        second, _ = storage_key_for(tenant, task, "отчёт.pdf")
        assert first != second

    def test_explicit_unique_is_stable(self):
        tenant, task = uuid4(), uuid4()
        first, name = storage_key_for(tenant, task, "отчёт.pdf", unique="abc123")
        second, _ = storage_key_for(tenant, task, "отчёт.pdf", unique="abc123")
        assert first == second
        assert first == f"{tenant}/{task}/abc123-{name}"

    def test_cyrillic_name_survives_only_outside_the_key(self):
        """Санитайзер съедает кириллицу целиком — это про путь, не про подпись.

        «отчёт.pdf» на диске становится просто «pdf»: NFKD + ASCII-ignore
        не оставляет от русского имени ничего. Поэтому импорт из внешнего
        трекера кладёт в `task_attachments.filename` ОРИГИНАЛ, а
        санитизированное имя живёт только внутри `storage_key`.
        """
        _key, sanitized = storage_key_for(uuid4(), uuid4(), "отчёт.pdf")
        assert sanitized == "pdf"
        # «№» переживает NFKD как «No» — единственный уцелевший кусок.
        _key, sanitized = storage_key_for(uuid4(), uuid4(), "Счёт №17 от 03.02.pdf")
        assert sanitized == "No17_03.02.pdf"

    def test_unique_does_not_escape_root(self):
        # Ключ собирается из наших же данных, но путь обязан остаться внутри.
        key, _ = storage_key_for(uuid4(), uuid4(), "a.pdf", unique="x")
        assert ".." not in key

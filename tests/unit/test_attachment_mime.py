"""resolve_mime — восстановление MIME из расширения ТОЛЬКО для .heic/.heif.

Десктопные браузеры шлют HEIC как application/octet-stream или без типа;
общий mimetypes.guess_type запрещён — он «спас» бы и опасные типы
(octet-stream + .svg → image/svg+xml), ломая fail-closed whitelist.
"""

from __future__ import annotations

from app.services.attachments import ALLOWED_MIME, resolve_mime


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


def test_sniff_renamed_executable_is_rejected():
    mz = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff\x00\x00"
    assert sniff_mismatch("image/png", mz) is True
    assert sniff_mismatch("image/jpeg", mz) is True
    assert sniff_mismatch("application/pdf", mz) is True
    assert sniff_mismatch("application/zip", mz) is True
    assert sniff_mismatch("application/msword", mz) is True
    assert sniff_mismatch("image/heic", mz) is True
    assert sniff_mismatch("image/webp", b"RIFF\x00\x00\x00\x00AVI LIST") is True


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

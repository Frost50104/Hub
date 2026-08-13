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

"""Хранение файлов материалов библиотеки (Ф1).

Layout (относительно attachments_root, тот же корень, что у task-вложений —
общий бэкап): {tenant_id}/learn/materials/{material_id}/v{N}-{filename}

Whitelist уже, чем у task-вложений: только документы/изображения (без
zip/json; SVG исключён — stored-XSS; видео придёт в Ф3a вместе с
media-инфраструктурой learn_media).
"""

from __future__ import annotations

from uuid import UUID

from app.services.attachments import _sanitize_filename, absolute_path

__all__ = ["LIBRARY_MIME", "absolute_path", "storage_key_for_version"]

LIBRARY_MIME: frozenset[str] = frozenset(
    {
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-powerpoint",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "image/png",
        "image/jpeg",
        "image/webp",
        "text/plain",
        "text/markdown",
        "text/csv",
    }
)


def storage_key_for_version(
    tenant_id: UUID, material_id: UUID, version_no: int, filename: str
) -> tuple[str, str]:
    """→ (storage_key относительно attachments_root, sanitized filename)."""
    sanitized = _sanitize_filename(filename)
    return f"{tenant_id}/learn/materials/{material_id}/v{version_no}-{sanitized}", sanitized

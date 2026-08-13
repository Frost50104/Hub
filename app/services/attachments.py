"""Attachment storage helpers — filename sanitization + safe file I/O.

Storage layout (relative to `settings.attachments_root`):
    {tenant_id}/{task_id}/{uuid}-{sanitized_filename}

`storage_key` in the DB is the path **relative** to attachments_root.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from uuid import UUID, uuid4

from app.config import get_settings

# A small but permissive MIME whitelist. Anything else → 415.
# Зеркалится клиентом (web/src/lib/attachments.ts::ATTACHMENT_ACCEPT) —
# менять ПАРОЙ, иначе accept-фильтр и сервер разъедутся.
ALLOWED_MIME: frozenset[str] = frozenset(
    {
        # Images. SVG намеренно исключён: это XML с поддержкой <script> —
        # stored-XSS вектор при любом inline-рендере.
        # HEIC/HEIF (фото iPhone) браузеры НЕ декодируют — сейчас вложения
        # отдаются только как скачивание (Content-Disposition: attachment);
        # появится inline-превью image/* — HEIC/HEIF из него исключить.
        "image/png",
        "image/jpeg",
        "image/webp",
        "image/gif",
        "image/heic",
        "image/heif",
        "image/heic-sequence",
        "image/heif-sequence",
        # Documents
        "application/pdf",
        "application/zip",
        "application/x-zip-compressed",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-powerpoint",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        # Text
        "text/plain",
        "text/markdown",
        "text/csv",
        # JSON
        "application/json",
    }
)


# Восстановление MIME из расширения — ТОЛЬКО для явно перечисленных типов.
# Никакого mimetypes.guess_type: общий маппинг «спас» бы и опасные типы
# (octet-stream + .svg → image/svg+xml), ломая fail-closed whitelist.
_EXT_FALLBACK_MIME: dict[str, str] = {
    ".heic": "image/heic",
    ".heif": "image/heif",
}


def resolve_mime(content_type: str | None, filename: str) -> str:
    """Нормализует заявленный клиентом MIME.

    Десктопные браузеры шлют .heic как application/octet-stream или вовсе
    без типа — для generic/пустого типа пытаемся восстановить MIME из
    расширения (только _EXT_FALLBACK_MIME). Параметры вида `; charset=…`
    отрезаются.
    """
    mime = (content_type or "").split(";")[0].strip().lower()
    if mime in ("", "application/octet-stream"):
        return _EXT_FALLBACK_MIME.get(
            Path(filename).suffix.lower(), mime or "application/octet-stream"
        )
    return mime


def _sanitize_filename(name: str) -> str:
    """Strip path components, normalize unicode, keep only [A-Za-z0-9._-].

    Returns a name no longer than 100 chars; falls back to `file` if empty.
    """
    # Drop directory parts the client might have sent.
    base = Path(name).name
    # NFKD then drop combining marks — turns «é» → «e», emoji → '' etc.
    nfkd = unicodedata.normalize("NFKD", base)
    ascii_only = nfkd.encode("ascii", "ignore").decode("ascii")
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", ascii_only).strip("._")[:100]
    return safe or "file"


def storage_key_for(tenant_id: UUID, task_id: UUID, filename: str) -> tuple[str, str]:
    """Return (storage_key_relative, sanitized_original_filename)."""
    sanitized = _sanitize_filename(filename)
    key = f"{tenant_id}/{task_id}/{uuid4().hex}-{sanitized}"
    return key, sanitized


def absolute_path(storage_key: str) -> Path:
    """Resolve `storage_key` (relative path) under attachments_root, refusing
    any traversal outside of root (defense in depth — keys are server-generated
    but it's cheap insurance)."""
    settings = get_settings()
    root = Path(settings.attachments_root).resolve()
    candidate = (root / storage_key).resolve()
    if not str(candidate).startswith(str(root) + "/") and candidate != root:
        raise ValueError(f"storage_key escapes attachments root: {storage_key}")
    return candidate

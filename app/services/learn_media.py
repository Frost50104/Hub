"""Медиа learn-домена (Ф3a): подписанные URL + хранение + проверки.

Почему подписи, а не Bearer: теги <video>/<img> и pdf-iframe не несут
Authorization-заголовок (crit-находка ревью плана). API выдаёт
короткоживущий URL `/api/media/{id}?e=<exp>&s=<hmac>`; GET проверяет
подпись (без JWT — работает и в iOS PWA standalone) и отдаёт файл через
nginx X-Accel-Redirect (Range/206 обрабатывает nginx, Python не стримит).

Layout: {tenant_id}/learn/media/{media_id}-{filename} под attachments_root
(общий бэкап backup-files.timer).

Видео: только mp4 (H.264/AAC — инструкция для HR), обязательный faststart
(moov-атом до mdat, иначе iOS качает весь файл до старта воспроизведения).
"""

from __future__ import annotations

import hashlib
import hmac
import os
import struct
import time
from pathlib import Path
from uuid import UUID

from app.config import get_settings
from app.services.attachments import _sanitize_filename, absolute_path

__all__ = [
    "MEDIA_MIME_KINDS",
    "absolute_path",
    "check_free_space",
    "mp4_has_faststart",
    "sign_media_path",
    "storage_key_for_media",
    "verify_media_signature",
]

MEDIA_MIME_KINDS: dict[str, str] = {
    "image/png": "image",
    "image/jpeg": "image",
    "image/webp": "image",
    "video/mp4": "video",
    "application/pdf": "pdf",
}


def _secret() -> bytes:
    settings = get_settings()
    if settings.media_url_secret:
        return settings.media_url_secret.encode()
    # Fallback: стабильный per-env секрет, не хранящийся отдельно.
    return hashlib.sha256(f"hub-media:{settings.database_url}".encode()).digest()


def _signature(media_id: UUID, exp: int) -> str:
    msg = f"{media_id}:{exp}".encode()
    return hmac.new(_secret(), msg, hashlib.sha256).hexdigest()[:32]


def sign_media_path(media_id: UUID, *, ttl_sec: int | None = None) -> str:
    """→ относительный подписанный путь `/api/media/{id}?e=…&s=…`."""
    settings = get_settings()
    exp = int(time.time()) + (ttl_sec or settings.media_url_ttl_sec)
    return f"/api/media/{media_id}?e={exp}&s={_signature(media_id, exp)}"


def verify_media_signature(media_id: UUID, exp: int, sig: str) -> bool:
    if exp < time.time():
        return False
    return hmac.compare_digest(_signature(media_id, exp), sig)


def storage_key_for_media(tenant_id: UUID, media_id: UUID, filename: str) -> tuple[str, str]:
    sanitized = _sanitize_filename(filename)
    return f"{tenant_id}/learn/media/{media_id}-{sanitized}", sanitized


def check_free_space(path: Path | None = None) -> int:
    """Свободные байты на разделе attachments_root."""
    settings = get_settings()
    target = path or Path(settings.attachments_root)
    # attachments_root может ещё не существовать (свежий env) — идём вверх.
    while not target.exists():
        target = target.parent
    st = os.statvfs(target)
    return st.f_bavail * st.f_frsize


def mp4_has_faststart(path: Path, *, scan_limit: int = 64) -> bool:
    """True, если moov-атом идёт раньше mdat (streaming-ready mp4).

    Читаем только заголовки top-level атомов (size+type), прыгая по файлу —
    без загрузки контента. Повреждённая структура → False (fail-closed).
    """
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            offset = 0
            for _ in range(scan_limit):
                if offset + 8 > size:
                    return False
                fh.seek(offset)
                header = fh.read(8)
                if len(header) < 8:
                    return False
                box_size = struct.unpack(">I", header[:4])[0]
                box_type = header[4:8]
                if box_type == b"moov":
                    return True
                if box_type == b"mdat":
                    return False
                if box_size == 1:  # 64-битный размер
                    ext = fh.read(8)
                    if len(ext) < 8:
                        return False
                    box_size = struct.unpack(">Q", ext)[0]
                elif box_size == 0:  # атом до конца файла
                    return False
                if box_size < 8:
                    return False
                offset += box_size
            return False
    except OSError:
        return False


def media_size_limit(kind: str, learn_settings: dict) -> int:
    if kind == "video":
        return int(learn_settings.get("video_max_bytes", 300 * 1024 * 1024))
    if kind == "pdf":
        return int(learn_settings.get("document_max_bytes", 50 * 1024 * 1024))
    return int(learn_settings.get("image_max_bytes", 10 * 1024 * 1024))

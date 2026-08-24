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
from typing import BinaryIO
from uuid import UUID

from app.config import get_settings
from app.services.attachments import _sanitize_filename, absolute_path

__all__ = [
    "MEDIA_MIME_KINDS",
    "absolute_path",
    "check_free_space",
    "mp4_duration_seconds",
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


# Шаг «времени выдачи»: внутри одного окна URL одного и того же файла
# получается ПОБАЙТОВО одинаковым.
_ISSUE_BUCKET_SEC = 3600


def sign_media_path(media_id: UUID, *, ttl_sec: int | None = None) -> str:
    """→ относительный подписанный путь `/api/media/{id}?e=…&s=…`.

    `exp` округляется вниз по сетке `_ISSUE_BUCKET_SEC`, поэтому повторный
    ответ той же ручки отдаёт ТОТ ЖЕ URL. Прежний `now + ttl` менялся каждую
    секунду: любой рефетч урока подставлял `<video>` новый `src`, браузер
    перезагружал элемент — позиция слетала на 0 и воспроизведение вставало на
    паузу (воспроизведено на staging 25.08 фокусом вкладки). Заодно попадания
    в HTTP-кэш перестают быть случайностью.

    Шаг не больше половины TTL — остаток жизни ссылки всегда ≥ ttl/2.
    """
    settings = get_settings()
    ttl = ttl_sec or settings.media_url_ttl_sec
    bucket = max(1, min(_ISSUE_BUCKET_SEC, ttl // 2))
    issued = (int(time.time()) // bucket) * bucket
    exp = issued + ttl
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


def mp4_duration_seconds(path: Path, *, scan_limit: int = 64) -> float | None:
    """Длительность mp4 из `moov → mvhd`, в секундах. None — прочитать не вышло.

    Сервер обязан знать длительность сам: гейт досмотра делит просмотренное на
    неё, и клиентское число может как открыть гейт раньше времени (занижение),
    так и навсегда заблокировать завершение (завышение всего в 1,12 раза уже
    делает 90% недостижимыми). Файл под media_id неизменяем — значит это
    физическая константа, а не то, что уточняют пингами.

    Ходим по тем же top-level боксам, что и `mp4_has_faststart`, затем на
    уровень глубже внутри `moov`. Любая аномалия → None: вызывающий откатится
    на клиентское значение (fail-open — иначе битый парсер запер бы курсы).
    """
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            moov = _find_box(fh, offset=0, limit=size, want=b"moov", scan_limit=scan_limit)
            if moov is None:
                return None
            moov_start, moov_end = moov
            mvhd = _find_box(
                fh, offset=moov_start, limit=moov_end, want=b"mvhd", scan_limit=scan_limit
            )
            if mvhd is None:
                return None
            fh.seek(mvhd[0])
            head = fh.read(12)  # version(1) + flags(3) + creation/modification
            if len(head) < 4:
                return None
            version = head[0]
            # v0: creation(4) modification(4) timescale(4) duration(4)
            # v1: creation(8) modification(8) timescale(4) duration(8)
            fh.seek(mvhd[0] + (4 + 16 if version == 1 else 4 + 8))
            raw = fh.read(12 if version == 1 else 8)
            if version == 1:
                if len(raw) < 12:
                    return None
                timescale = struct.unpack(">I", raw[:4])[0]
                duration = struct.unpack(">Q", raw[4:12])[0]
            else:
                if len(raw) < 8:
                    return None
                timescale, duration = struct.unpack(">II", raw[:8])
            if timescale <= 0 or duration <= 0:
                return None
            seconds = duration / timescale
            # 24 часа — та же граница, что у VideoProgressBody: всё, что больше,
            # это не учебный ролик, а разъехавшийся timescale.
            if not (0 < seconds <= 24 * 3600):
                return None
            return seconds
    except (OSError, struct.error):
        return None


def _find_box(
    fh: BinaryIO, *, offset: int, limit: int, want: bytes, scan_limit: int
) -> tuple[int, int] | None:
    """(начало содержимого, конец бокса) для первого бокса `want` на уровне.

    `offset` — начало уровня (для top-level это 0, для вложенного — начало
    содержимого родителя).
    """
    for _ in range(scan_limit):
        if offset + 8 > limit:
            return None
        fh.seek(offset)
        header = fh.read(8)
        if len(header) < 8:
            return None
        box_size = struct.unpack(">I", header[:4])[0]
        box_type = header[4:8]
        body = offset + 8
        if box_size == 1:  # 64-битный размер
            ext = fh.read(8)
            if len(ext) < 8:
                return None
            box_size = struct.unpack(">Q", ext)[0]
            body = offset + 16
        elif box_size == 0:  # бокс до конца файла
            box_size = limit - offset
        if box_size < 8 or offset + box_size > limit:
            return None
        if box_type == want:
            return body, offset + box_size
        offset += box_size
    return None


def media_size_limit(kind: str, learn_settings: dict) -> int:
    if kind == "video":
        return int(learn_settings.get("video_max_bytes", 300 * 1024 * 1024))
    if kind == "pdf":
        return int(learn_settings.get("document_max_bytes", 50 * 1024 * 1024))
    return int(learn_settings.get("image_max_bytes", 10 * 1024 * 1024))

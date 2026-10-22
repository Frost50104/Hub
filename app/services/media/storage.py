"""Файлы конвейера: временная папка задания, публикация результата, свободное
место, уборка сирот, host-wide замок на один ffmpeg на машину.

Tmp живёт ПОД `attachments_root` (`<tenant>/learn/media/.tmp/<job_id>/`), а
не в `/tmp`: та же файловая система, поэтому публикация — атомарный
`os.replace`, а не копирование гигабайтного файла. `.tmp` исключается из
бэкапа файлов (`scripts/backup-files.sh`).
"""

from __future__ import annotations

import fcntl
import os
import shutil
import time
from pathlib import Path
from uuid import UUID

import structlog

from app.config import Settings
from app.services.attachments import absolute_path
from app.services.learn_media import check_free_space

log = structlog.get_logger("media.storage")

TMP_DIR_NAME = ".tmp"
_EXTENSION_ONLY = frozenset({"mov", "mp4", "m4v", "webm", "mkv", "avi"})


class NoSpace(Exception):
    def __init__(self, free: int, need: int) -> None:
        super().__init__(f"мало места: свободно {free // 2**20} МБ, нужно {need // 2**20} МБ")
        self.free = free
        self.need = need


def tmp_dir(settings: Settings, tenant_id: UUID, job_id: UUID) -> Path:
    root = Path(settings.attachments_root) / str(tenant_id) / "learn" / "media"
    return root / TMP_DIR_NAME / str(job_id)


def make_tmp_dir(settings: Settings, tenant_id: UUID, job_id: UUID) -> Path:
    path = tmp_dir(settings, tenant_id, job_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def remove_tmp_dir(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def ensure_free_space(settings: Settings, need_bytes: int) -> None:
    """Порог как у загрузки (`media_min_free_bytes`) ПЛЮС место под работу:
    исходник + выход + промежуточные файлы. Диск общий с Postgres."""
    free = check_free_space()
    need = int(settings.media_min_free_bytes) + int(need_bytes)
    if free < need:
        raise NoSpace(free, need)


def sweep_orphan_tmp(settings: Settings, *, max_age_hours: float | None = None) -> int:
    """Удалить папки заданий старше `media_tmp_max_age_hours` — остатки
    процессов, убитых без `finally` (OOM, SIGKILL). → сколько удалено."""
    root = Path(settings.attachments_root)
    age = (settings.media_tmp_max_age_hours if max_age_hours is None else max_age_hours) * 3600
    cutoff = time.time() - age
    removed = 0
    if not root.exists():
        return 0
    for tmp in root.glob(f"*/learn/media/{TMP_DIR_NAME}/*"):
        try:
            if tmp.is_dir() and tmp.stat().st_mtime < cutoff:
                shutil.rmtree(tmp, ignore_errors=True)
                removed += 1
        except OSError:
            continue
    if removed:
        log.info("media.tmp_swept", removed=removed)
    return removed


def publish(src: Path, storage_key: str) -> Path:
    """Атомарно положить готовый файл под его ключ (та же ФС — `os.replace`)."""
    dest = absolute_path(storage_key)
    dest.parent.mkdir(parents=True, exist_ok=True)
    os.replace(src, dest)
    return dest


def derived_storage_key(tenant_id: UUID, media_id: UUID, name: str) -> str:
    """Ключ производного файла (чистовик, VTT, нормализованный MP4)."""
    return f"{tenant_id}/learn/media/{media_id}-{name}"


def stem_of_storage_key(storage_key: str, media_id: UUID) -> str:
    """`<id>-<stem>.<ext>` → `<stem>`; для имён вроде `<id>-video.mov` даёт `video`."""
    name = Path(storage_key).name
    prefix = f"{media_id}-"
    if name.startswith(prefix):
        name = name[len(prefix) :]
    # Не `Path.stem`: у имени `.mov` (пустое имя + расширение) он вернул бы `.mov`.
    stem = name.rsplit(".", 1)[0] if "." in name else name
    stem = stem.strip()
    # Кириллическое имя санитайзер режет до одного расширения («Запись.mov» →
    # `mov`) — такой «стем» именем не считаем.
    if not stem or stem.lower() in _EXTENSION_ONLY:
        return "video"
    return stem


class HostLock:
    """Один ffmpeg на машину: прод и staging делят два ядра, и два x264 рядом
    с STT положили бы API. `flock` на общем файле; замок — на время задания."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._fd: int | None = None

    def acquire(self) -> bool:
        if self._fd is not None:
            return True
        try:
            fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o666)
        except OSError as exc:
            # /run/lock недоступен (dev-машина) — замок рядом с временными файлами.
            fallback = Path("/tmp") / self.path.name  # noqa: S108 — осознанный фолбэк
            log.warning("media.lock_fallback", path=str(self.path), err=str(exc)[:120])
            fd = os.open(fallback, os.O_RDWR | os.O_CREAT, 0o666)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            return False
        self._fd = fd
        return True

    def release(self) -> None:
        if self._fd is None:
            return
        try:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
        finally:
            os.close(self._fd)
            self._fd = None

    @property
    def held(self) -> bool:
        return self._fd is not None

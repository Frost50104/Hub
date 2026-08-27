"""Attachment storage helpers — filename sanitization + safe file I/O.

Storage layout (relative to `settings.attachments_root`):
    {tenant_id}/{task_id}/{uuid}-{sanitized_filename}

`storage_key` in the DB is the path **relative** to attachments_root.
"""

from __future__ import annotations

import contextlib
import re
import unicodedata
from pathlib import Path
from uuid import UUID, uuid4

import structlog
from fastapi import HTTPException, UploadFile, status

from app.config import get_settings
from app.models.attachment import TaskAttachment

log = structlog.get_logger("services.attachments")

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


# Магические байты для семейств с однозначной сигнатурой. Проверяем ТОЛЬКО их:
# text/*, json, csv сигнатуры не имеют (UTF-16/BOM — легальны) и пропускаются.
# Ложный 415 хуже пропущенного файла, поэтому список консервативный.
_MAGIC: dict[str, tuple[bytes, ...]] = {
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/gif": (b"GIF87a", b"GIF89a"),
    # RIFF....WEBP — проверяется отдельно (offset 8).
    "image/webp": (b"RIFF",),
    # zip-семейство: docx/xlsx/pptx/zip. Пустой архив (PK\x05\x06) — тоже zip.
    "application/zip": (b"PK\x03\x04", b"PK\x05\x06"),
    "application/x-zip-compressed": (b"PK\x03\x04", b"PK\x05\x06"),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (b"PK\x03\x04",),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": (b"PK\x03\x04",),
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": (b"PK\x03\x04",),
    # OLE2 (doc/xls/ppt).
    "application/msword": (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",),
    "application/vnd.ms-excel": (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",),
    "application/vnd.ms-powerpoint": (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",),
}
_HEIC_MIMES = frozenset(
    {"image/heic", "image/heif", "image/heic-sequence", "image/heif-sequence"}
)
# Сколько байт нужно читать для sniff_mismatch: PDF ищем в первом килобайте
# (допустим BOM/мусор до `%PDF`), остальным хватает 12.
SNIFF_HEAD_BYTES = 1024


def sniff_mismatch(mime: str, head: bytes) -> bool:
    """True, если первые байты файла ПРОТИВОРЕЧАТ заявленному MIME.

    Whitelist по заявленному типу клиент обходит переименованием (`MZ…` под
    именем `.png` проходил 201 — QA-0821 #11). Проверяются только семейства с
    однозначной сигнатурой; неизвестный MIME / пустой head → False (решает
    whitelist ALLOWED_MIME, не сниффер).
    """
    if not head:
        return False
    if mime == "application/pdf":
        return b"%PDF" not in head[:SNIFF_HEAD_BYTES]
    if mime == "image/webp":
        return not (head.startswith(b"RIFF") and head[8:12] == b"WEBP")
    if mime in _HEIC_MIMES:
        # ISO BMFF: размер бокса (4 байта) + 'ftyp' с 4-го байта.
        return head[4:8] != b"ftyp"
    magics = _MAGIC.get(mime)
    if magics is None:
        return False
    return not any(head.startswith(m) for m in magics)


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


def storage_key_for(
    tenant_id: UUID, task_id: UUID, filename: str, *, unique: str | None = None
) -> tuple[str, str]:
    """Return (storage_key_relative, sanitized_original_filename).

    `unique=None` — случайный сегмент, поведение ручки загрузки. Импорт из
    внешнего трекера передаёт стабильный идентификатор вложения: тогда
    повторный прогон пишет в ТОТ ЖЕ путь и не оставляет осиротевших файлов
    на диске (удалять их некому — sweeper'а в Hub нет).
    """
    sanitized = _sanitize_filename(filename)
    key = f"{tenant_id}/{task_id}/{unique or uuid4().hex}-{sanitized}"
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


def purge_blobs(keys: list[str]) -> None:
    """Снять файлы с диска — вне транзакции и best-effort. СИНХРОННАЯ.

    Звать только через `asyncio.to_thread`: прод крутится на ОДНОМ
    uvicorn-воркере, и сотни синхронных `unlink()` в event loop подвесили бы
    всё приложение.

    Порядок «сначала commit, потом unlink» неслучаен: файловая система не
    транзакционна, и обратный порядок при неудачном commit оставил бы строки
    БД, указывающие на несуществующие файлы. Провал unlink после успешного
    commit — это утечка байтов, а не рассинхрон; ровно эта терпимость уже
    принята для одиночного вложения (app/api/attachments.py).

    `rmtree` по каталогу задачи не берём: `absolute_path` защищает от выхода
    за root, но не от «валидный, но не тот» путь — ошибка в одной строке БД
    при rmtree сносит поддерево, при unlink теряется один файл.
    """
    dirs: set[Path] = set()
    for key in keys:
        try:
            path = absolute_path(key)
        except ValueError:
            log.warning("blob.purge.bad_storage_key", key=key)
            continue
        try:
            path.unlink(missing_ok=True)
            dirs.add(path.parent)
        except OSError as exc:
            log.warning("blob.purge.unlink_failed", key=key, err=str(exc))
    for directory in dirs:
        with contextlib.suppress(OSError):
            directory.rmdir()  # только пустые; ENOTEMPTY игнорируем


async def store_upload(
    file: UploadFile,
    *,
    tenant_id: UUID,
    task_id: UUID,
    uploaded_by: UUID,
) -> TaskAttachment:
    """Проверить файл и записать его на диск; вернуть НЕсохранённую строку.

    Единственная точка проверок для ВСЕХ путей загрузки — ручки вложений и
    формы обратной связи. Расходиться им нельзя: whitelist без сниффинга
    магических байт пропускает html под видом png, а лимит без потоковой
    записи заполняет диск до отказа.

    Строку в сессию не добавляем — это дело вызывающего: он решает, в какой
    транзакции и с какой лентой она поедет. Частичный файл при ошибке
    удаляется здесь же: осиротевший блоб убирать в Hub некому.
    """
    settings = get_settings()
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Имя файла обязательно"
        )
    mime = resolve_mime(file.content_type, file.filename)
    if mime not in ALLOWED_MIME:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Тип файла {mime!r} не разрешён",
        )
    # Сниффинг магических байт: читаем голову и возвращаем курсор — стриминг
    # ниже считает лимит размера с нуля.
    head = await file.read(SNIFF_HEAD_BYTES)
    await file.seek(0)
    if sniff_mismatch(mime, head):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Содержимое файла не соответствует заявленному типу",
        )

    storage_key, sanitized_name = storage_key_for(tenant_id, task_id, file.filename)
    dest = absolute_path(storage_key)
    dest.parent.mkdir(parents=True, exist_ok=True)

    max_bytes = settings.attachment_max_bytes
    written = 0
    try:
        with dest.open("wb") as fh:
            while True:
                chunk = await file.read(64 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    fh.close()
                    dest.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"Файл больше лимита {max_bytes // (1024 * 1024)} МБ",
                    )
                fh.write(chunk)
    except HTTPException:
        raise
    except Exception as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Не удалось сохранить файл",
        ) from exc

    return TaskAttachment(
        id=uuid4(),
        tenant_id=tenant_id,
        task_id=task_id,
        uploaded_by=uploaded_by,
        filename=sanitized_name,
        mime=mime,
        size_bytes=written,
        storage_key=storage_key,
    )

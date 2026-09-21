"""Attachment storage helpers — filename sanitization + safe file I/O.

Storage layout (relative to `settings.attachments_root`):
    {tenant_id}/{task_id}/{uuid}-{sanitized_filename}

`storage_key` in the DB is the path **relative** to attachments_root.
"""

from __future__ import annotations

import asyncio
import contextlib
import errno
import os
import re
import shutil
import unicodedata
from pathlib import Path
from typing import Literal
from urllib.parse import quote
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
        # Видео (ОС 15.09: сотрудник не смог приложить запись к задаче).
        # Три контейнера покрывают то, чем снимают на деле: Android и запись
        # экрана дают mp4, iPhone — mov, браузерная запись — webm. Формат
        # проигрывается не везде (mov не понимает Chrome), но вложение — это
        # прежде всего файл: что не заиграло, то скачивается.
        # Faststart, в отличие от медиа уроков, НЕ требуем: камера Android
        # пишет moov в конец, и требование воспроизвело бы ту же жалобу.
        "video/mp4",
        "video/quicktime",
        "video/webm",
    }
)


# Потолок размера зависит от вида файла: документам хватает 20 МБ, видео —
# нет (минута 1080p с телефона ≈ 100 МБ). Зеркало клиента —
# `web/src/lib/attachmentTypes.ts::attachmentSizeError`, менять ПАРОЙ.
def attachment_size_limit(mime: str) -> int:
    settings = get_settings()
    if mime.startswith("video/"):
        return settings.attachment_video_max_bytes
    return settings.attachment_max_bytes


# Восстановление MIME из расширения — ТОЛЬКО для явно перечисленных типов.
# Никакого mimetypes.guess_type: общий маппинг «спас» бы и опасные типы
# (octet-stream + .svg → image/svg+xml), ломая fail-closed whitelist.
_EXT_FALLBACK_MIME: dict[str, str] = {
    ".heic": "image/heic",
    ".heif": "image/heif",
    # Видео попадает сюда по той же причине, что и HEIC: файловые менеджеры
    # Android и часть десктопных браузеров отдают его как octet-stream, и без
    # восстановления человек получил бы 415 на обычной записи с телефона.
    # Восстанавливать эти три можно ровно потому, что у них есть однозначная
    # сигнатура и сразу за `resolve_mime` идёт `sniff_mismatch`; у `.svg`
    # сигнатуры нет — поэтому его в карте нет и быть не должно.
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
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
# mp4 и mov — тот же контейнер ISO-BMFF, что и HEIC: бокс `ftyp` с 4-го байта.
_ISOBMFF_MIMES = frozenset({"video/mp4", "video/quicktime"})
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
    if mime in _HEIC_MIMES or mime in _ISOBMFF_MIMES:
        # ISO BMFF: размер бокса (4 байта) + 'ftyp' с 4-го байта.
        return head[4:8] != b"ftyp"
    if mime == "video/webm":
        # EBML-заголовок Matroska/WebM.
        return not head.startswith(b"\x1a\x45\xdf\xa3")
    magics = _MAGIC.get(mime)
    if magics is None:
        return False
    return not any(head.startswith(m) for m in magics)


# Символы, которых не должно быть в имени файла: разделители путей, служебные
# знаки Windows и управляющие байты.
_UNSAFE_IN_NAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')
_MULTISPACE = re.compile(r"\s+")
# Расширение по mime — ЗЕРКАЛО `web/src/lib/materialFileName.ts::MIME_EXT`.
EXT_BY_MIME: dict[str, str] = {
    "application/pdf": "pdf",
    "application/msword": "doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.ms-excel": "xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.ms-powerpoint": "ppt",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
    "image/heic": "heic",
    "image/heif": "heif",
    "text/plain": "txt",
    "text/markdown": "md",
    "text/csv": "csv",
    "application/zip": "zip",
    "video/mp4": "mp4",
    "video/quicktime": "mov",
    "video/webm": "webm",
}
_BARE_EXT = re.compile(r"^[A-Za-z0-9]{1,5}$")


def display_filename(name: str) -> str:
    """Имя для ПОКАЗА и скачивания: юникод сохраняем, опасное убираем.

    Отдельно от `_sanitize_filename` намеренно. Тот собирает имя для ФАЙЛОВОЙ
    СИСТЕМЫ и выбрасывает всё не-ASCII — на кириллическом имени от него
    остаётся один хвост: «ЛДМО.xlsx» → «xlsx», «Отчет_final.xlsx» → «final.xlsx».
    Пока оба имени были одним значением, в БД уезжало искалеченное, и человек
    получал файл «xlsx» (в Chrome — «xlsx.xlsx»), который Windows не открывает
    (ОС 14.09). Путь в хранилище по-прежнему ASCII — его считает
    `_sanitize_filename`, а это имя живёт только в колонке и в заголовке
    Content-Disposition (Starlette сам кодирует не-ASCII по RFC 5987).

    Хвостовые точки и пробелы срезаются: Windows их не сохраняет.
    """
    # И «/», и «\\»: браузер шлёт только базовое имя, но multipart можно
    # набить руками, а на POSIX `Path` про windows-разделитель не знает.
    base = Path(name.replace("\\", "/")).name
    cleaned = _MULTISPACE.sub(" ", _UNSAFE_IN_NAME.sub(" ", base)).strip()
    # Вычищенный символ не должен оставлять пробел перед точкой расширения:
    # «отчёт*?.pdf» → «отчёт.pdf», а не «отчёт .pdf».
    cleaned = re.sub(r"\s+(?=\.)", "", cleaned)
    cleaned = cleaned.rstrip(". ")[:150].strip()
    return cleaned or "file"


def download_filename(stored: str | None, *, mime: str | None, fallback: str) -> str:
    """Имя для скачивания, чинящее уже испорченные строки в БД.

    Зеркало `web/src/lib/materialFileName.ts::materialDownloadName` — одно
    правило на сервер и на системную шторку «Поделиться» в iOS PWA.

    Если в имени есть точка не первым символом — отдаём как есть. Иначе (на
    проде это 58 материалов и 19 вложений, у которых в колонке лежит голое
    «xlsx»/«docx») собираем имя из осмысленного `fallback` — названия
    материала — и расширения по mime; если mime незнаком, расширением служит
    сама испорченная строка.
    """
    stored_clean = display_filename(stored or "") if stored else ""
    if stored_clean == "file":
        stored_clean = ""
    if len(stored_clean) > 1 and "." in stored_clean and not stored_clean.startswith("."):
        return stored_clean
    ext = EXT_BY_MIME.get(mime or "")
    if ext is None and _BARE_EXT.match(stored_clean):
        ext = stored_clean.lower()
    base = display_filename(fallback)
    return f"{base}.{ext}" if ext else base


def content_disposition(filename: str, *, disposition_type: str = "inline") -> str:
    """Готовый заголовок `Content-Disposition` для РУЧНОЙ сборки ответа.

    Заголовки HTTP кодируются latin-1, поэтому кириллица, вписанная в
    `filename="…"` напрямую, роняет ответ в `UnicodeEncodeError` (500). Там,
    где ответ собирает Starlette (`FileResponse(filename=…)`), это делается за
    нас; там, где заголовок пишем руками — X-Accel у медиа, CSV-экспорты —
    нужно звать эту функцию. Для не-ASCII отдаётся форма RFC 5987
    (`filename*=utf-8''…`), которую понимают все живые браузеры.
    """
    quoted = quote(filename)
    if quoted == filename:
        safe = filename.replace('"', "")
        return f'{disposition_type}; filename="{safe}"'
    return f"{disposition_type}; filename*=utf-8''{quoted}"


def _sanitize_filename(name: str) -> str:
    """Strip path components, normalize unicode, keep only [A-Za-z0-9._-].

    Имя для ФАЙЛОВОЙ СИСТЕМЫ (`storage_key`), не для показа: не-ASCII здесь
    теряется целиком, поэтому в БД должно уезжать `display_filename`.

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


CloneOutcome = Literal["linked", "copied", "missing"]


def clone_blob(src_key: str, dst_key: str) -> CloneOutcome:
    """Второй путь к тем же байтам: жёсткая ссылка, иначе полная копия. СИНХРОННАЯ.

    Для копирования проекта по шаблону (0060). Делить один `storage_key` между
    двумя строками нельзя — `purge_blobs` удаляет ПО ПУТИ, и удаление шаблона
    унесло бы файл у живого проекта (ровно поэтому повтор задач вложения не
    копирует). Разные пути на один inode безопасны: `unlink` снимает только
    свою ссылку. Опасна лишь запись ПОВЕРХ существующего пути — её делают
    только разовые импорты (`storage_key_for(..., unique=…)`), живые загрузки
    всегда пишут в свежий uuid-путь.

    Звать через `asyncio.to_thread`: прод крутится на одном воркере.
    Нет исходного файла — `missing`: вложение пропускается, отчёт его называет.
    """
    src = absolute_path(src_key)
    dst = absolute_path(dst_key)
    if not src.is_file():
        return "missing"
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(src, dst)
        return "linked"
    except OSError as exc:
        # EXDEV — другой раздел, EMLINK — потолок ссылок, EPERM — ФС без
        # жёстких ссылок. Всё остальное — настоящая ошибка.
        if exc.errno not in (errno.EXDEV, errno.EMLINK, errno.EPERM, errno.ENOTSUP):
            raise
    shutil.copyfile(src, dst)
    return "copied"


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
    max_bytes: int | None = None,
) -> TaskAttachment:
    """Проверить файл и записать его на диск; вернуть НЕсохранённую строку.

    Единственная точка проверок для ВСЕХ путей загрузки — ручки вложений и
    формы обратной связи. Расходиться им нельзя: whitelist без сниффинга
    магических байт пропускает html под видом png, а лимит без потоковой
    записи заполняет диск до отказа.

    `max_bytes` — ПОТОЛОК ВЫЗЫВАЮЩЕГО, а не общая настройка. Гигабайтное видео
    легально во вложении задачи и нелегально в форме обратной связи: у той своя
    арифметика набора (10 файлов, суммарный вес) и свой потолок тела в nginx.
    Пока лимит читался внутри, расширение его для видео молча подняло бы и
    форму. `None` — «по виду файла», `attachment_size_limit(mime)`.

    Строку в сессию не добавляем — это дело вызывающего: он решает, в какой
    транзакции и с какой лентой она поедет. Частичный файл при ошибке
    удаляется здесь же: осиротевший блоб убирать в Hub некому.
    """
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

    limit = attachment_size_limit(mime) if max_bytes is None else max_bytes
    written = 0
    try:
        with dest.open("wb") as fh:
            while True:
                chunk = await file.read(64 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > limit:
                    fh.close()
                    dest.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"Файл больше лимита {limit // (1024 * 1024)} МБ",
                    )
                # Запись — В ПОТОК, а не в event loop: гигабайтное видео это
                # 16 тысяч синхронных write(), и когда page cache упрётся в
                # writeback, каждый встанет на десятки миллисекунд. Прод
                # крутится на ОДНОМ uvicorn-воркере; Starlette по той же
                # причине пишет свой спул через threadpool.
                await asyncio.to_thread(fh.write, chunk)
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
        # В колонку — ЧИТАЕМОЕ имя, в путь — ASCII-санитайзер: иначе
        # кириллическое имя приезжало в БД обрезанным до расширения.
        filename=display_filename(file.filename or sanitized_name),
        mime=mime,
        size_bytes=written,
        storage_key=storage_key,
    )

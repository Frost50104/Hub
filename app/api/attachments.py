"""Task attachments API — multipart upload + streaming download + delete.

Видео (ОС 15.09) отдаётся НЕ этой же ручкой скачивания: тег `<video>` не шлёт
`Authorization`, а качать гигабайт в память JS, чтобы показать его в карточке,
нельзя. Поэтому у вложений появился второй путь отдачи — подписанный URL без
JWT плюс `X-Accel-Redirect`, ровно как у медиа уроков: Range/206 (перемотку)
обрабатывает nginx, Python не стримит.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse, Response
from signaris_auth import Principal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import tenant_scoped_session
from app.deps import enforce_rate_limit, get_db_template_page, require_auth
from app.models.attachment import TaskAttachment
from app.models.shadow import ShadowUser
from app.models.task import Task
from app.schemas.attachment import AttachmentResponse
from app.services.activity_writer import record_activity
from app.services.attachments import (
    absolute_path,
    attachment_size_limit,
    content_disposition,
    download_filename,
    resolve_mime,
    store_upload,
)
from app.services.learn_media import check_free_space, issue_token, verify_token
from app.services.personal_projects import require_task_access
from app.services.project_access import is_hub_admin, open_template_if_hidden

router = APIRouter(tags=["attachments"])


def _sign_key(attachment_id: UUID) -> str:
    """Ключ подписи. Префикс отделяет пространство вложений от медиа уроков:
    подпись, выданную на один ресурс, нельзя предъявить другому."""
    return f"attach:{attachment_id}"


def preview_url_for(attachment_id: UUID, mime: str) -> str | None:
    """Адрес для `<video>` — только видео и только ему.

    Картинкам его не выдаём сознательно: inline-показ image/* в карточке — это
    отдельная задача, и в whitelist'е записано, что при её появлении HEIC/HEIF
    из превью надо исключить (браузеры их не декодируют).
    """
    if not mime.startswith("video/"):
        return None
    exp, sig = issue_token(_sign_key(attachment_id), get_settings().media_url_ttl_sec)
    return f"/api/attachments/{attachment_id}/file?e={exp}&s={sig}"


async def _fetch_task_visible(
    db: AsyncSession, task_id: UUID, principal: Principal
) -> Task:
    task = await db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена")
    await require_task_access(db, task, principal)
    return task


async def _list_enriched(db: AsyncSession, task_id: UUID) -> list[AttachmentResponse]:
    rows = await db.execute(
        select(
            TaskAttachment.id,
            TaskAttachment.task_id,
            TaskAttachment.filename,
            TaskAttachment.mime,
            TaskAttachment.size_bytes,
            TaskAttachment.uploaded_by,
            TaskAttachment.created_at,
            ShadowUser.email,
            ShadowUser.full_name,
        )
        .join(
            ShadowUser,
            (ShadowUser.employee_id == TaskAttachment.uploaded_by)
            & (ShadowUser.deleted_at.is_(None)),
            isouter=True,
        )
        .where(TaskAttachment.task_id == task_id)
        .order_by(TaskAttachment.created_at)
    )
    return [
        AttachmentResponse(
            id=r.id,
            task_id=r.task_id,
            filename=r.filename,
            mime=r.mime,
            size_bytes=r.size_bytes,
            uploaded_by=r.uploaded_by,
            created_at=r.created_at,
            uploader_email=r.email,
            uploader_full_name=r.full_name,
            preview_url=preview_url_for(r.id, r.mime),
        )
        for r in rows.all()
    ]


@router.get(
    "/tasks/{task_id}/attachments", response_model=list[AttachmentResponse]
)
async def list_attachments(
    task_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db_template_page),
) -> list[AttachmentResponse]:
    await _fetch_task_visible(db, task_id, principal)
    return await _list_enriched(db, task_id)


def _assert_free_space(file: UploadFile) -> None:
    """Не дать загрузке добить диск, общий с Postgres/WAL.

    Проверка именно ЗДЕСЬ, а не внутри `store_upload`: к моменту вызова ручки
    FastAPI уже разобрал multipart, и Starlette положила файл во временный
    (спул больше 1 МБ уезжает на диск). То есть `check_free_space` уже видит
    место, съеденное спулом, и запас нужен ровно на ОДНУ копию — ту, которую
    сейчас запишет `store_upload`. Отсюда `+ file.size`, а не `+ лимит`:
    двадцатикилобайтный скриншот не должен требовать гигабайта свободного.
    """
    settings = get_settings()
    # `file.size` заполняет парсер multipart, и в живом запросе он есть всегда.
    # Если его вдруг нет — считаем по ПОТОЛКУ вида файла, а не по нулю: гейт,
    # который при неизвестном размере молча превращается в «места хватит»,
    # хуже отсутствующего, потому что выглядит рабочим.
    mime = resolve_mime(file.content_type, file.filename or "")
    need = settings.media_min_free_bytes + (file.size or attachment_size_limit(mime))
    if check_free_space() < need:
        raise HTTPException(
            status_code=status.HTTP_507_INSUFFICIENT_STORAGE,
            detail="На сервере мало места — загрузка временно недоступна. "
            "Сообщите администратору.",
        )


async def _accept_upload(
    db: AsyncSession, task_id: UUID, file: UploadFile, principal: Principal
) -> AttachmentResponse:
    """Общее тело обеих ручек загрузки — фиксированной и старой, по задаче."""
    await enforce_rate_limit(
        bucket="attach:upload",
        employee_id=str(principal.employee_id),
        limit=30,
        window_sec=60,
    )
    # Фиксированный адрес `POST /attachments` несёт `task_id` полем формы, а
    # не в пути — область шаблона (0060) открываем явно.
    await open_template_if_hidden(db, principal, task_id=task_id, mode="edit")
    task = await _fetch_task_visible(db, task_id, principal)
    # Edit-permission required — uploading mutates a task.
    await require_task_access(
        db, task, principal, allow=("owner", "editor")
    )
    _assert_free_space(file)

    attachment = await store_upload(
        file,
        tenant_id=task.tenant_id,
        task_id=task.id,
        uploaded_by=principal.employee_id,
    )
    db.add(attachment)
    await db.flush()
    await record_activity(
        db,
        tenant_id=task.tenant_id,
        task_id=task.id,
        actor_id=principal.employee_id,
        kind="attached",
        payload={
            "attachment_id": str(attachment.id),
            "filename": attachment.filename,
            "size_bytes": attachment.size_bytes,
        },
    )
    await db.commit()
    out = await _list_enriched(db, task.id)
    matching = next((a for a in out if a.id == attachment.id), None)
    if matching is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Не удалось перечитать вложение",
        )
    return matching


@router.post(
    "/attachments",
    response_model=AttachmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_attachment(
    task_id: UUID = Form(...),
    file: UploadFile = File(...),
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db_template_page),
) -> AttachmentResponse:
    """Загрузка вложения. Путь ФИКСИРОВАН, и это требование nginx, а не вкус.

    Потолок тела задаётся локацией, а видео не влезает в общие 25 МБ. Сделать
    локацию под прежний адрес `/api/tasks/{uuid}/attachments` нельзя: он живёт
    под `location ^~ /api/`, а модификатор `^~` ОТМЕНЯЕТ проверку
    regex-локаций — блок `location ~ ^/api/tasks/…` прошёл бы `nginx -t` и не
    сработал никогда. Поднимать же потолок всему `/api/tasks/` значит
    разрешить гигабайтное тело в `PATCH /tasks/{id}`. Отсюда адрес без
    переменных и точная локация `location = /api/attachments` — тем же
    приёмом и по той же причине сделан `location = /api/learn/media`.
    """
    return await _accept_upload(db, task_id, file, principal)


@router.post(
    "/tasks/{task_id}/attachments",
    response_model=AttachmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_attachment_legacy(
    task_id: UUID,
    file: UploadFile = File(...),
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db_template_page),
) -> AttachmentResponse:
    """Прежний адрес — для бандлов, выданных до этой правки.

    PWA обновляется неделями (`registerType: 'prompt'`), и вчерашняя вкладка
    обязана продолжать грузить документы. Видео она не предложит — у неё свой
    список расширений, а на этом пути nginx всё равно режет тело на 25 МБ.
    """
    return await _accept_upload(db, task_id, file, principal)


@router.get("/attachments/{attachment_id}/file")
async def serve_attachment(
    attachment_id: UUID,
    e: int = Query(...),
    s: str = Query(..., max_length=64),
    dl: int = 0,
) -> Response:
    """Отдача по подписи, без JWT — чтобы файл мог запросить сам тег `<video>`.

    Права проверяются на ВЫДАЧЕ адреса (`preview_url` попадает только в ответ
    списка вложений, а тот стоит за `require_task_access`), здесь — только
    подпись, как у медиа уроков. Сессия поэтому `bypass_rls=True`: без токена
    tenant-контекста нет, а `get_db` его требует.
    """
    if not verify_token(_sign_key(attachment_id), e, s):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Ссылка недействительна или истекла",
        )

    async with tenant_scoped_session(None, bypass_rls=True) as session:
        attachment = await session.get(TaskAttachment, attachment_id)
    if attachment is None or not attachment.storage_key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Файл не найден")

    path = absolute_path(attachment.storage_key)
    name = download_filename(
        attachment.filename, mime=attachment.mime, fallback="вложение"
    )
    # `dl=1` — та же ссылка, но «сохранить», а не «показать». Отдельный
    # параметр, а не отдельная ручка: скачивание гигабайтного видео обязано
    # идти мимо JS (прежний путь тянул файл в память вкладки через
    # responseType:'blob'), а показ в <video> требует именно inline.
    disposition = "attachment" if dl else "inline"
    settings = get_settings()
    if not settings.media_accel_enabled:
        if not path.is_file():
            raise HTTPException(
                status_code=status.HTTP_410_GONE, detail="Файл на диске отсутствует"
            )
        # Range/206 здесь делает Starlette; в проде файл отдаёт nginx (ниже).
        return FileResponse(
            path,
            media_type=attachment.mime,
            filename=name,
            content_disposition_type=disposition,
        )

    return Response(
        status_code=200,
        headers={
            "X-Accel-Redirect": f"/_protected_media/{attachment.storage_key}",
            "Content-Type": attachment.mime,
            # Заголовок собираем САМИ, значит и кодируем сами: кириллица в
            # filename="…" роняет ответ в latin-1 (500).
            "Content-Disposition": content_disposition(
                name, disposition_type=disposition
            ),
            "Cache-Control": "private, max-age=3600",
        },
    )


@router.get("/attachments/{attachment_id}/download")
async def download_attachment(
    attachment_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db_template_page),
) -> FileResponse:
    attachment = await db.get(TaskAttachment, attachment_id)
    if attachment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Файл не найден")
    # Reuse task-visibility guard.
    await open_template_if_hidden(db, principal, task_id=attachment.task_id, mode="view")
    task = await db.get(Task, attachment.task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Файл не найден")
    await require_task_access(db, task, principal)

    path = absolute_path(attachment.storage_key)
    if not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_410_GONE, detail="Файл на диске отсутствует"
        )
    return FileResponse(
        path=path,
        media_type=attachment.mime,
        # Имена, испорченные прежним ASCII-санитайзером (в БД лежит голое
        # «docx»), чиним на отдаче: без расширения Windows файл не открывает.
        filename=download_filename(
            attachment.filename, mime=attachment.mime, fallback="вложение"
        ),
    )


@router.delete("/attachments/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_attachment(
    attachment_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db_template_page),
) -> None:
    attachment = await db.get(TaskAttachment, attachment_id)
    if attachment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Файл не найден")
    await open_template_if_hidden(db, principal, task_id=attachment.task_id, mode="edit")
    task = await db.get(Task, attachment.task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Файл не найден")

    # Uploader can always delete. Otherwise need owner/editor in the project,
    # or hub:admin (covered by require_project_role(allow=owner,editor)).
    if attachment.uploaded_by != principal.employee_id and not is_hub_admin(principal):
        await require_task_access(
            db, task, principal, allow=("owner", "editor")
        )

    path = absolute_path(attachment.storage_key)
    if path.is_file():
        try:
            path.unlink()
        except OSError:
            pass  # We still drop the DB row — orphans get cleaned by a future sweeper.

    await record_activity(
        db,
        tenant_id=task.tenant_id,
        task_id=task.id,
        actor_id=principal.employee_id,
        kind="unattached",
        payload={"attachment_id": str(attachment.id), "filename": attachment.filename},
    )
    await db.delete(attachment)
    await db.commit()

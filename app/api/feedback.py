"""Обратная связь из настроек: текст + необязательный файл → задача.

Ручка ОДНА и намеренно узкая: она не даёт выбрать проект, исполнителя или
приоритет — всё это решает сервер. Иначе форма, открытая каждому сотруднику,
превратилась бы в способ писать задачи в любой проект в обход прав.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Annotated

import structlog
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from pydantic import BaseModel
from signaris_auth import Principal
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.deps import enforce_rate_limit, get_db, require_auth
from app.schemas.task import TaskCreate
from app.services.attachments import purge_blobs, store_upload
from app.services.feedback import (
    attach_feedback_label,
    feedback_description,
    feedback_title,
    find_feedback_project,
    project_owner_id,
)
from app.services.project_access import ensure_project_member
from app.services.task_assignees import (
    apply_assignee_side_effects,
    set_task_assignees,
)
from app.services.task_watchers import ensure_watcher
from app.services.tasks import create_task_record
from app.services.timefmt import fmt_dt

log = structlog.get_logger("feedback")

router = APIRouter(tags=["feedback"])

TEXT_MAX = 5000
# Сколько файлов принимаем за одну отправку.
#
# Форма открыта КАЖДОМУ сотруднику, и ограничение частоты здесь одно —
# 5 отправок в час. Без потолка на количество это 5 × сколько-угодно файлов по
# 20 МБ с одной учётки: диск VPS кончится быстрее, чем кто-нибудь заметит.
# Десять — с запасом на «серия скриншотов одного бага»; упрётся кто-то —
# поднять здесь и в `web/src/lib/feedback.ts` ПАРОЙ.
MAX_FILES = 10
# Потолок на всю отправку. Каждый файл и так ограничен `attachment_max_bytes`
# (20 МБ), но десять таких — это 200 МБ в одном запросе на машине с 2 ГБ.
TOTAL_BYTES_MAX = 50 * 1024 * 1024


class FeedbackResponse(BaseModel):
    delivered: bool = True


@router.post(
    "/feedback", response_model=FeedbackResponse, status_code=status.HTTP_201_CREATED
)
async def send_feedback(
    request: Request,
    text: Annotated[str, Form(max_length=TEXT_MAX)],
    files: Annotated[list[UploadFile] | None, File()] = None,
    file: Annotated[UploadFile | None, File()] = None,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> FeedbackResponse:
    """Сообщение + вложения → задача в проекте развития.

    Полей для файлов ДВА, и это не небрежность: `files` — нынешний клиент,
    `file` — вчерашний бандл. PWA живёт закешированной версией до применения
    обновления, и отправка «с телефона со скриншотом» не должна падать 422
    у того, кто ещё не перезапустил приложение. Поле `file` снимать не раньше,
    чем через пару релизов.
    """
    # Форма доступна всем сотрудникам, а задача ложится в чужой проект —
    # ограничение частоты здесь не «на всякий случай», а единственная защита.
    await enforce_rate_limit(
        bucket="feedback:send",
        employee_id=str(principal.employee_id),
        limit=5,
        window_sec=3600,
    )
    message = text.strip()
    if not message:
        # 422 как у остальных схем: пустое сообщение — ошибка ввода, а не
        # «отправлено».
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Напишите, что случилось — пустое сообщение отправить нельзя",
        )

    # Оба поля в один список; пустые части multipart браузер шлёт как файл без
    # имени — их отбрасываем, иначе получилось бы вложение «file» на 0 байт.
    uploads = [f for f in [*(files or []), file] if f is not None and f.filename]
    if len(uploads) > MAX_FILES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"За раз можно приложить не больше {MAX_FILES} файлов",
        )

    project = await find_feedback_project(db, principal.tenant_id)
    settings = get_settings()

    task = await create_task_record(
        db,
        principal=principal,
        project_id=project.id,
        body=TaskCreate(
            title=feedback_title(message),
            description=feedback_description(
                message,
                author_name=principal.full_name or principal.email,
                author_email=principal.email,
                when=fmt_dt(datetime.now(UTC), "%d.%m.%Y %H:%M"),
                version=settings.app_version,
                user_agent=request.headers.get("user-agent"),
            ),
        ),
        # watch_creator=False: побочки create молчат и членства не дают —
        # подписка и viewer-членство автора идут явными шагами ниже (02.09).
        watch_creator=False,
    )
    await attach_feedback_label(
        db, tenant_id=principal.tenant_id, project_id=project.id, task_id=task.id
    )

    # Автор следит за своим сообщением (решение владельца 02.09): подписка
    # даёт пуши по комментариям/статусу, а viewer-членство в проекте обратной
    # связи открывает карточку по ссылке из пуша — без членства любой
    # task-эндпоинт отвечал бы 404, и уведомления вели бы в тупик.
    # Следствие принято владельцем: автор видит проект обратной связи целиком.
    await ensure_watcher(
        db,
        task_id=task.id,
        tenant_id=principal.tenant_id,
        employee_id=principal.employee_id,
        reason="creator",
    )
    await ensure_project_member(
        db,
        project_id=project.id,
        tenant_id=principal.tenant_id,
        employee_id=principal.employee_id,
        added_by=principal.employee_id,
    )

    owner_id = await project_owner_id(db, project.id)
    if owner_id is not None:
        # Отдельным шагом ради `notify=True`: внутри create побочки исполнителя
        # намеренно молчат, и владелец не узнал бы о сообщении.
        diff = await set_task_assignees(
            db,
            task=task,
            employee_ids=[owner_id],
            actor_id=principal.employee_id,
        )
        await apply_assignee_side_effects(
            db,
            task=task,
            diff=diff,
            actor_id=principal.employee_id,
            actor_name=principal.full_name or principal.email,
            notify=True,
            record=True,
        )

    if uploads:
        # Файлы пишутся на диск ДО commit: при ошибке задача не создаётся.
        # Частичный блоб убирает сам `store_upload`, а вот УЖЕ ЗАПИСАННЫЕ
        # соседи — забота этого цикла: транзакция откатится, строк не будет, и
        # снять их с диска станет некому (sweeper'а в Hub нет).
        written: list[str] = []
        total = 0
        try:
            for upload in uploads:
                attachment = await store_upload(
                    upload,
                    tenant_id=principal.tenant_id,
                    task_id=task.id,
                    uploaded_by=principal.employee_id,
                )
                written.append(attachment.storage_key)
                total += attachment.size_bytes
                if total > TOTAL_BYTES_MAX:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=(
                            "Вместе файлы весят больше "
                            f"{TOTAL_BYTES_MAX // (1024 * 1024)} МБ — "
                            "отправьте их несколькими сообщениями"
                        ),
                    )
                db.add(attachment)
        except Exception:
            await asyncio.to_thread(purge_blobs, written)
            raise

    await db.commit()
    log.info(
        "feedback.received",
        task_id=str(task.id),
        project=project.key,
        employee_id=str(principal.employee_id),
        files=len(uploads),
    )
    return FeedbackResponse()

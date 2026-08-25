"""Первая задача сотрудника: ознакомиться с инструкцией по Hub.

Заводится ОДИН раз — в момент создания личного проекта
(`personal_projects.ensure_personal_project`). Это и есть отметка «первый
вход»: партиальный UNIQUE `uq_projects_personal_owner` гарантирует, что проект
создаётся ровно однажды, поэтому отдельного флага в БД не нужно. Тем, у кого
личный проект уже был к моменту выкатки, задачу раздаёт разовый
`app/jobs/backfill_guide_task.py`.

Ссылка в описании ведёт на «Учётную запись», а НЕ на файл инструкции: hub-роль
живёт в JWT и в БД её нет, так что бэкфилл не смог бы выбрать нужный документ,
а прямая ссылка протухала бы при смене роли. Кнопка в профиле всегда открывает
правильную.
"""

from __future__ import annotations

from uuid import UUID

import structlog
from signaris_auth import Principal
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import Task
from app.schemas.task import TaskCreate
from app.services.tasks import create_task_record

log = structlog.get_logger(__name__)

GUIDE_TASK_TITLE = "Изучите инструкцию по работе в Hub"
GUIDE_TASK_DESCRIPTION = (
    "Эту задачу завёл Hub — она одна и только для вас.\n\n"
    "Инструкция открывается из профиля: "
    "[Учётная запись → «Посмотреть инструкцию»](/settings/account). "
    "Там же лежат ваши данные и сертификаты.\n\n"
    "Прочитали — отметьте задачу выполненной."
)


async def create_guide_task(
    db: AsyncSession, *, principal: Principal, project_id: UUID
) -> Task | None:
    """Завести задачу в личном проекте. БЕЗ commit'а; исключений не выпускает.

    Единственный вызывающий на живом пути — `ensure_personal_project` внутри
    `GET /api/me`, то есть вход в приложение. Падение здесь отрезало бы НОВОГО
    сотрудника от Hub целиком, поэтому ошибка = «задачи нет», а не 500:
    инструкция всё равно доступна кнопкой в профиле.
    """
    try:
        async with db.begin_nested():
            return await create_task_record(
                db,
                principal=principal,
                project_id=project_id,
                body=TaskCreate(
                    title=GUIDE_TASK_TITLE,
                    description=GUIDE_TASK_DESCRIPTION,
                ),
            )
    except Exception:  # noqa: BLE001 — вход в приложение важнее этой задачи
        log.warning(
            "onboarding.guide_task_failed",
            employee_id=str(principal.employee_id),
            exc_info=True,
        )
        return None


async def has_guide_task(db: AsyncSession, project_id: UUID) -> bool:
    """Есть ли уже задача-инструкция в этом личном проекте.

    Только для разового бэкфилла: на живом пути идемпотентность даёт сам момент
    создания проекта. Сравнение по заголовку — этого достаточно одноразовому
    прогону, но означает, что сотрудник, удаливший задачу ДО повторного
    запуска, получит её снова; поэтому `--apply` гоняем один раз.
    """
    found = await db.execute(
        select(func.count())
        .select_from(Task)
        .where(Task.project_id == project_id, Task.title == GUIDE_TASK_TITLE)
    )
    return bool(found.scalar_one())

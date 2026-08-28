"""Создание проекта — общий путь для ручки POST /projects и для личного
пространства (`services/personal_projects.py`).

Здесь только доменная работа: строка проекта + owner-членство создателя
(колонок у нового проекта нет — см. `services/stages.py`). Права, подбор ключа
и commit — на вызывающем (тот же контракт, что у
`services/tasks.py::create_task_record`). Вынесено из ручки, чтобы два пути
создания не разъехались на первой же новой дефолтной сущности.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project, ProjectMember

# Один текст на все отказы «проект в архиве»: создание задачи
# (`services/tasks.py::create_task_record`) и перенос в архивный проект
# (`services/task_move.py::assert_movable`). Разные формулировки одного правила
# читаются как разные правила.
ARCHIVED_PROJECT_DETAIL = "Проект в архиве — сначала восстановите его"


def assert_project_accepts_tasks(project: Project) -> None:
    """409, если в проект больше не заводят задачи.

    Гейт стоит ТОЛЬКО на создании. Правку существующей задачи в архивном
    проекте не трогаем сознательно: она ничего не теряет — задача уже есть и
    открывается по ссылке, — а запрет сломал бы массовые правки ассистента
    посреди плана. Колонки, метки и кастом-поля в архиве тоже по-прежнему
    создаются: пустая колонка ничего не теряет (см. docs/tech-debt/open.md).

    Заводить задачи было можно всегда, и прятал это только клиент; живой путь
    мимо клиента — ассистент, который резолвит проект по имени. Созданная так
    задача выпадает из поиска (`api/search.py` фильтрует архивные проекты) и из
    списков, то есть с точки зрения человека работа исчезает.
    """
    if project.archived_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=ARCHIVED_PROJECT_DETAIL
        )


async def create_project_record(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    created_by: UUID,
    name: str,
    key: str,
    description: str | None = None,
    personal_owner_id: UUID | None = None,
) -> Project:
    """Проект + этапы + owner-членство БЕЗ commit'а и БЕЗ проверки прав.

    `personal_owner_id` — только для личного пространства; значение обязано
    приходить из `principal.employee_id`, никогда из тела запроса (см.
    инвариант в `app/models/project.py`).
    """
    project = Project(
        id=uuid4(),
        tenant_id=tenant_id,
        key=key,
        name=name,
        description=description,
        created_by=created_by,
        personal_owner_id=personal_owner_id,
    )
    db.add(project)
    await db.flush()
    # Колонок у нового проекта НЕТ. Четыре стартовые («К выполнению», «В
    # работе», «На проверке», «Готово») выглядели готовой раскладкой, которую
    # никто не выбирал; теперь доска пуста, пока человек не создаст первую
    # колонку сам, а задачи до этого живут без колонки (0046).
    db.add(
        ProjectMember(
            id=uuid4(),
            tenant_id=tenant_id,
            project_id=project.id,
            employee_id=created_by,
            role="owner",
            added_by=created_by,
        )
    )
    await db.flush()
    return project

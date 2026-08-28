"""Обратная связь из настроек → задача в проекте развития.

Форма открыта КАЖДОМУ сотруднику, а задача ложится в проект, участником
которого он, как правило, не является. Отсюда три особенности, каждая
намеренная:

- задача заводится тем же `services/tasks.py::create_task_record`, что и любая
  другая, но с `watch_creator=False`: подписка автора на задачу в проекте, куда
  у него нет доступа, приводила бы его по пушу в 403;
- исполнитель — ВЛАДЕЛЕЦ проекта, и назначается он отдельным шагом, а не полем
  `assignee_ids`: внутри create побочки зовутся с `notify=False`, и пуш «вам
  назначили задачу» не ушёл бы;
- метка «Обратная связь» заводится идемпотентно: две одновременные отправки не
  должны падать на UNIQUE(project_id, name).
"""

from __future__ import annotations

from uuid import UUID, uuid4

import structlog
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.project import Project, ProjectMember
from app.models.task import TaskLabel, TaskLabelAssignment

log = structlog.get_logger("feedback")

FEEDBACK_LABEL = "Обратная связь"
# Нейтрально-серый, как у меток, приехавших из секций (0047): амбер — цвет
# акцента, и раздавать его автоматическим меткам нельзя.
FEEDBACK_LABEL_COLOR = "#8A8A99"
TITLE_MAX = 120


def feedback_title(text: str) -> str:
    """Заголовок задачи — первая строка сообщения, обрезанная по слову.

    Заголовок читают в списке и в уведомлении, поэтому это ПЕРВАЯ строка, а не
    первые 120 символов сплошняком: люди начинают с сути и жмут Enter.
    """
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if len(first) <= TITLE_MAX:
        return first
    cut = first[: TITLE_MAX - 1]
    # Рвём по границе слова, если она близко: «Не работает кноп…» читается, а
    # «Не работает кно…» выглядит как сбой рендера.
    space = cut.rfind(" ")
    if space > TITLE_MAX - 30:
        cut = cut[:space]
    return cut.rstrip(" ,.;:—-") + "…"


def feedback_description(
    text: str,
    *,
    author_name: str,
    author_email: str,
    when: str,
    version: str,
    user_agent: str | None,
) -> str:
    """Текст сообщения + подпись «кто, когда, откуда».

    Подпись обязательна: задача попадает к владельцу продукта, а он должен
    уметь вернуться к человеку с вопросом и понять, на какой сборке это было.
    Устройство — то, чего человек сам не напишет, а для «у меня кнопка не
    нажимается» это половина диагноза.
    """
    lines = [text.strip(), "", "---", f"От: {author_name} ({author_email})", f"Когда: {when}"]
    lines.append(f"Версия Hub: {version}")
    if user_agent:
        lines.append(f"Устройство: {user_agent[:300]}")
    return "\n".join(lines)


async def find_feedback_project(db: AsyncSession, tenant_id: UUID) -> Project:
    """Проект приёма обратной связи в тенанте отправителя.

    По КЛЮЧУ из настроек, а не по id: ключ переживает переименование проекта и
    читается в конфиге. Тенант в условии явно — ключ уникален лишь внутри
    тенанта, и полагаться на одну только RLS в поиске «куда писать» не стоит.

    Архивный проект = проекта нет: см. комментарий у ветки ниже.
    """
    key = get_settings().feedback_project_key
    row = (
        await db.execute(
            select(Project, Project.archived_at.is_not(None).label("archived")).where(
                Project.tenant_id == tenant_id, Project.key == key
            )
        )
    ).first()
    # Архивный проект приравниваем к отсутствующему: задачи туда не заводятся
    # (`services/projects.py::assert_project_accepts_tasks`), и без этой ветки
    # сотрудник, пишущий в поддержку, получил бы 409 «Проект в архиве» — про
    # проект, которого он не выбирал и не видел.
    project = row[0] if row is not None and not row.archived else None
    if project is None:
        # 503, а не 500: отправитель ни при чём, а владельцу нужен внятный след.
        log.error(
            "feedback.project_unavailable",
            key=key,
            tenant_id=str(tenant_id),
            reason="archived" if row is not None else "missing",
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Обратная связь пока не настроена — напишите владельцу продукта напрямую",
        )
    return project


async def project_owner_id(db: AsyncSession, project_id: UUID) -> UUID | None:
    """Владелец проекта — будущий исполнитель задачи.

    Берём из членства, а не из конфига с почтой: смена владельца проекта не
    должна требовать выката. `None` (владельца сняли) — не ошибка: задача
    просто останется без исполнителя, потерять сообщение из-за этого нельзя.
    """
    row = await db.execute(
        select(ProjectMember.employee_id)
        .where(ProjectMember.project_id == project_id, ProjectMember.role == "owner")
        .order_by(ProjectMember.added_at)
        .limit(1)
    )
    return row.scalar_one_or_none()


async def ensure_feedback_label(
    db: AsyncSession, *, tenant_id: UUID, project_id: UUID
) -> UUID:
    """Метка «Обратная связь» — создать или найти. Идемпотентно.

    `ON CONFLICT DO NOTHING` конфликтную строку НЕ возвращает (урок миграции
    0047), поэтому id всегда добираем отдельным SELECT'ом по (project_id, name).
    """
    await db.execute(
        pg_insert(TaskLabel)
        .values(
            id=uuid4(),
            tenant_id=tenant_id,
            project_id=project_id,
            name=FEEDBACK_LABEL,
            color=FEEDBACK_LABEL_COLOR,
        )
        .on_conflict_do_nothing(constraint="uq_task_labels_project_name")
    )
    return (
        await db.execute(
            select(TaskLabel.id).where(
                TaskLabel.project_id == project_id, TaskLabel.name == FEEDBACK_LABEL
            )
        )
    ).scalar_one()


async def attach_feedback_label(
    db: AsyncSession, *, tenant_id: UUID, project_id: UUID, task_id: UUID
) -> UUID:
    label_id = await ensure_feedback_label(db, tenant_id=tenant_id, project_id=project_id)
    await db.execute(
        pg_insert(TaskLabelAssignment)
        .values(task_id=task_id, label_id=label_id, tenant_id=tenant_id)
        .on_conflict_do_nothing()
    )
    return label_id

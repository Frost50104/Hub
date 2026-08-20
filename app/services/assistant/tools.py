"""Реестр инструментов ассистента.

Модель не может выполнить произвольное действие: она выбирает из этого
списка, аргументы валидируются pydantic'ом, а идентификаторы резолвятся
через `context.py` — то есть только среди объектов, которые сотрудник и так
вправе видеть. Это же и защита от инъекций: текст внутри задачи не может
расширить набор операций.

Порог подтверждения (решение владельца, ОС по макету Claude Design):
`kind="read"` и правка ОДНОЙ задачи выполняются сразу; создание, архивация,
комментарий и любое массовое изменение уходят в карточку плана.

`delete_task` в реестре нет намеренно: удаление необратимо, а отмены у
исполненного плана по брифу не предусмотрено. Архивация закрывает тот же
сценарий и откатывается одной кнопкой в трекере.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.models.project import Project, ProjectMember
from app.models.shadow import ShadowUser
from app.models.task import Task
from app.services.assistant.context import (
    NotFound,
    ToolContext,
    resolve_person,
    resolve_project,
    resolve_task,
    visible_projects_stmt,
)
from app.services.task_assignees import (
    assignee_exists,
    has_no_assignees,
    load_assignees,
)

MSK = ZoneInfo("Europe/Moscow")

STATUS_RU = {
    "todo": "К выполнению",
    "in_progress": "В работе",
    "in_review": "На проверке",
    "done": "Готово",
}
PRIORITY_RU = {
    "low": "Низкий",
    "medium": "Обычный",
    "high": "Высокий",
    "urgent": "Срочный",
}

TaskStatusArg = Literal["todo", "in_progress", "in_review", "done"]
TaskPriorityArg = Literal["low", "medium", "high", "urgent"]


def parse_due(value: str | None) -> datetime | None:
    """«2026-08-22» → полдень по Москве, как это делает карточка задачи
    (`new Date(val + 'T12:00:00')` в TaskDetailDrawer).

    Полночь брать нельзя: в UTC она уезжает на предыдущий день, и срок,
    поставленный ассистентом, показался бы в трекере на сутки раньше.
    """
    if not value:
        return None
    raw = value.strip()
    try:
        if len(raw) == 10:
            naive = datetime.strptime(raw, "%Y-%m-%d").replace(hour=12)
            return naive.replace(tzinfo=MSK).astimezone(UTC)
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise NotFound(f"Не понял дату «{value}» — нужен вид 2026-08-22") from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=MSK)
    return parsed.astimezone(UTC)


def fmt_due(value: datetime | None) -> str | None:
    if value is None:
        return None
    local = value.astimezone(MSK)
    months = (
        "января", "февраля", "марта", "апреля", "мая", "июня",
        "июля", "августа", "сентября", "октября", "ноября", "декабря",
    )
    days = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")
    return f"{local.day} {months[local.month - 1]}, {days[local.weekday()]}"


# ─── Аргументы ──────────────────────────────────────────────────────────────


class SearchTasksArgs(BaseModel):
    query: str | None = Field(default=None, description="Слова из заголовка задачи")
    project: str | None = Field(default=None, description="Название или ключ проекта")
    assignee: str | None = Field(default=None, description="ФИО исполнителя или «я»")
    status: TaskStatusArg | None = None
    priority: TaskPriorityArg | None = None
    overdue: bool | None = Field(default=None, description="Только просроченные")
    unassigned: bool | None = Field(default=None, description="Только без исполнителя")
    limit: int = Field(default=20, ge=1, le=50)


class TaskRefArgs(BaseModel):
    task: str = Field(description="Номер задачи вида UPPETITTV-207")


class ProjectRefArgs(BaseModel):
    project: str = Field(description="Название или ключ проекта")


class MyTasksArgs(BaseModel):
    status: TaskStatusArg | None = None
    overdue_only: bool = False


class FindPeopleArgs(BaseModel):
    query: str = Field(default="", description="Часть имени или пусто — все")


class KnowledgeArgs(BaseModel):
    query: str = Field(min_length=2, description="Вопрос по регламентам и обучению")


class CreateTaskArgs(BaseModel):
    project: str
    title: str = Field(min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=20_000)
    assignees: list[str] = Field(default_factory=list, max_length=10)
    due_at: str | None = Field(default=None, description="Дата YYYY-MM-DD")
    priority: TaskPriorityArg = "medium"


class UpdateTaskArgs(BaseModel):
    task: str
    title: str | None = Field(default=None, min_length=1, max_length=500)
    status: TaskStatusArg | None = None
    priority: TaskPriorityArg | None = None
    due_at: str | None = None
    assignees: list[str] | None = Field(default=None, max_length=10)


class UpdateTasksArgs(BaseModel):
    tasks: list[str] = Field(min_length=1, max_length=50)
    status: TaskStatusArg | None = None
    priority: TaskPriorityArg | None = None
    due_at: str | None = None
    assignees: list[str] | None = Field(default=None, max_length=10)


class CommentArgs(BaseModel):
    task: str
    # Потолок зеркалит CommentCreate.body: расходиться им нельзя, иначе
    # план соберётся, а исполнение упадёт валидацией.
    text: str = Field(min_length=1, max_length=4000)


# ─── Общие помощники ────────────────────────────────────────────────────────


def denied(reason: str, who_can: list[dict[str, str]] | None = None) -> dict[str, Any]:
    """Отказ по правам — ДАННЫЕ для модели, а не исключение.

    Модель обязана назвать причину и подсказать, кого попросить: макет рисует
    ровно это, и «просто 403» лишил бы сотрудника следующего шага.
    """
    return {"denied": True, "reason": reason, "who_can": who_can or []}


async def project_managers(ctx: ToolContext, project_id: UUID) -> list[dict[str, str]]:
    rows = (
        await ctx.db.execute(
            select(ShadowUser.full_name, ProjectMember.role)
            .join(ShadowUser, ShadowUser.employee_id == ProjectMember.employee_id)
            .where(
                ProjectMember.project_id == project_id,
                ProjectMember.role.in_(("owner", "editor")),
                ShadowUser.deleted_at.is_(None),
            )
            .order_by(ProjectMember.role)
            .limit(5)
        )
    ).all()
    role_ru = {"owner": "владелец", "editor": "редактор"}
    return [
        {"name": name or "—", "role": role_ru.get(role, role)} for name, role in rows
    ]


async def can_edit_project(ctx: ToolContext, project_id: UUID) -> bool:
    if ctx.is_admin:
        return True
    role = (
        await ctx.db.execute(
            select(ProjectMember.role).where(
                ProjectMember.project_id == project_id,
                ProjectMember.employee_id == ctx.employee_id,
            )
        )
    ).scalar_one_or_none()
    return role in ("owner", "editor")


async def serialize_task(ctx: ToolContext, task: Task, project_key: str) -> dict[str, Any]:
    """Компактное представление задачи ДЛЯ МОДЕЛИ: без описаний и вложений —
    в контекст должно влезать двадцать задач, а не две."""
    assignees = (await load_assignees(ctx.db, [task.id])).get(task.id, [])
    now = datetime.now(UTC)
    overdue_days = 0
    if task.due_at and task.status != "done" and task.due_at < now:
        overdue_days = (now - task.due_at).days
    return {
        "key": f"{project_key}-{task.seq}",
        "title": task.title,
        "status": STATUS_RU[task.status],
        "priority": PRIORITY_RU[task.priority],
        "assignees": [a.full_name or a.email or "—" for a in assignees],
        "due": fmt_due(task.due_at),
        "overdue_days": overdue_days or None,
        "url": f"/projects/{task.project_id}?task={task.id}",
    }


# ─── Инструменты чтения ─────────────────────────────────────────────────────


async def t_search_tasks(ctx: ToolContext, a: SearchTasksArgs) -> dict[str, Any]:
    projects = visible_projects_stmt(ctx).subquery()
    stmt = (
        select(Task, projects.c.key)
        .join(projects, projects.c.id == Task.project_id)
        .where(Task.archived_at.is_(None))
    )
    if a.project:
        stmt = stmt.where(Task.project_id == (await resolve_project(ctx, a.project)).id)
    if a.query:
        stmt = stmt.where(Task.title.ilike(f"%{a.query}%"))
    if a.status:
        stmt = stmt.where(Task.status == a.status)
    if a.priority:
        stmt = stmt.where(Task.priority == a.priority)
    if a.assignee:
        who = (
            ctx.employee_id
            if a.assignee.strip().lower() in ("я", "мне", "me")
            else (await resolve_person(ctx, a.assignee)).employee_id
        )
        stmt = stmt.where(assignee_exists(who))
    if a.unassigned:
        stmt = stmt.where(has_no_assignees())
    if a.overdue:
        stmt = stmt.where(Task.due_at < datetime.now(UTC), Task.status != "done")
    rows = (
        await ctx.db.execute(
            stmt.order_by(Task.due_at.asc().nulls_last(), Task.created_at.desc()).limit(a.limit)
        )
    ).all()
    return {
        "count": len(rows),
        "tasks": [await serialize_task(ctx, t, key) for t, key in rows],
    }


async def t_get_task(ctx: ToolContext, a: TaskRefArgs) -> dict[str, Any]:
    task = await resolve_task(ctx, a.task)
    project = await ctx.db.get(Project, task.project_id)
    data = await serialize_task(ctx, task, project.key if project else "?")
    data["description"] = (task.description or "")[:2000] or None
    data["project"] = project.name if project else None
    return data


async def t_project_summary(ctx: ToolContext, a: ProjectRefArgs) -> dict[str, Any]:
    project = await resolve_project(ctx, a.project)
    now = datetime.now(UTC)
    base = select(func.count()).select_from(Task).where(
        Task.project_id == project.id, Task.archived_at.is_(None)
    )
    by_status = {
        s: (await ctx.db.execute(base.where(Task.status == s))).scalar_one()
        for s in ("todo", "in_progress", "in_review", "done")
    }
    overdue = (
        await ctx.db.execute(base.where(Task.due_at < now, Task.status != "done"))
    ).scalar_one()
    week_ago = now - timedelta(days=7)
    created_week = (await ctx.db.execute(base.where(Task.created_at >= week_ago))).scalar_one()
    done_week = (
        await ctx.db.execute(base.where(Task.completed_at >= week_ago))
    ).scalar_one()
    unassigned = (await ctx.db.execute(base.where(has_no_assignees()))).scalar_one()
    overdue_list = (
        await ctx.db.execute(
            select(Task)
            .where(
                Task.project_id == project.id,
                Task.archived_at.is_(None),
                Task.due_at < now,
                Task.status != "done",
            )
            .order_by(Task.due_at.asc())
            .limit(5)
        )
    ).scalars().all()
    return {
        "project": project.name,
        "key": project.key,
        "by_status": {STATUS_RU[k]: v for k, v in by_status.items()},
        "overdue_count": overdue,
        "unassigned_count": unassigned,
        "created_last_week": created_week,
        "completed_last_week": done_week,
        "overdue_examples": [await serialize_task(ctx, t, project.key) for t in overdue_list],
    }


async def t_my_tasks(ctx: ToolContext, a: MyTasksArgs) -> dict[str, Any]:
    projects = visible_projects_stmt(ctx).subquery()
    stmt = (
        select(Task, projects.c.key)
        .join(projects, projects.c.id == Task.project_id)
        .where(Task.archived_at.is_(None), assignee_exists(ctx.employee_id))
    )
    if a.status:
        stmt = stmt.where(Task.status == a.status)
    if a.overdue_only:
        stmt = stmt.where(Task.due_at < datetime.now(UTC), Task.status != "done")
    rows = (
        await ctx.db.execute(stmt.order_by(Task.due_at.asc().nulls_last()).limit(30))
    ).all()
    return {
        "count": len(rows),
        "tasks": [await serialize_task(ctx, t, key) for t, key in rows],
    }


async def t_list_projects(ctx: ToolContext, a: BaseModel) -> dict[str, Any]:
    rows = (await ctx.db.execute(visible_projects_stmt(ctx).limit(50))).scalars().all()
    return {
        "projects": [
            {"name": p.name, "key": p.key, "can_edit": await can_edit_project(ctx, p.id)}
            for p in rows
        ]
    }


async def t_find_people(ctx: ToolContext, a: FindPeopleArgs) -> dict[str, Any]:
    """Только имя и роль в проектах. Email и телефон модели не отдаём —
    ассистент говорит с внешним LLM-провайдером."""
    stmt = select(ShadowUser).where(ShadowUser.deleted_at.is_(None))
    if a.query.strip():
        stmt = stmt.where(ShadowUser.full_name.ilike(f"%{a.query.strip()}%"))
    rows = (await ctx.db.execute(stmt.order_by(ShadowUser.full_name).limit(20))).scalars().all()
    return {"people": [{"name": u.full_name or "—"} for u in rows]}


async def t_search_knowledge(ctx: ToolContext, a: KnowledgeArgs) -> dict[str, Any]:
    """База знаний: тот же retrieval Ф6 с фильтром аудитории.

    Импорт локальный — `app.api.ai` тянет провайдера LLM, а модуль
    инструментов импортируется и в тестах без ключей.
    """
    if ctx.profile is None:
        return {
            "error": "У сотрудника нет учебного профиля — база знаний недоступна",
            "documents": [],
        }
    from app.api.ai import retrieve_lexical

    chunks = await retrieve_lexical(
        ctx.db, question=a.query, profile_id=ctx.profile.id, limit=4
    )
    return {
        "documents": [
            {"title": c.title, "url": c.url_path, "text": c.content[:1500]} for c in chunks
        ]
    }


# ─── Инструменты записи ─────────────────────────────────────────────────────


_SELF_WORDS = {"я", "мне", "меня", "себя", "me"}


async def _resolve_assignees(ctx: ToolContext, names: list[str]) -> list[ShadowUser]:
    """«Дмитрию», «на меня» → сотрудники. Неоднозначное имя всплывает
    исключением ДО любой записи, поэтому резолвим весь список заранее."""
    out: list[ShadowUser] = []
    for name in names:
        if name.strip().lower() in _SELF_WORDS:
            me = await ctx.db.get(ShadowUser, ctx.employee_id)
            if me is not None:
                out.append(me)
                continue
        out.append(await resolve_person(ctx, name))
    return out


async def t_create_task(ctx: ToolContext, a: CreateTaskArgs) -> dict[str, Any]:
    """Создание — ВСЕГДА через план: возвращает предложение, не результат."""
    project = await resolve_project(ctx, a.project)
    if not await can_edit_project(ctx, project.id):
        return denied(
            f"в проекте «{project.name}» у вас роль наблюдателя — создавать задачи там нельзя",
            await project_managers(ctx, project.id),
        )
    people = await _resolve_assignees(ctx, a.assignees)
    due = parse_due(a.due_at)
    fields = [
        {"label": "Проект", "value": project.name, "chip": "key", "chip_text": project.key},
        {"label": "Заголовок", "value": a.title},
    ]
    if people:
        fields.append(
            {
                "label": "Исполнитель" if len(people) == 1 else "Исполнители",
                "value": ", ".join(p.full_name or "—" for p in people),
                "chip": "who",
            }
        )
    if due:
        fields.append({"label": "Срок", "value": fmt_due(due)})
    fields.append(
        {"label": "Приоритет", "value": PRIORITY_RU[a.priority], "chip": "priority",
         "chip_text": a.priority}
    )
    return {
        "__plan__": {
            "tool": "create_task",
            "scope": "создание задачи · 1 объект",
            "args": {
                "project_id": str(project.id),
                "title": a.title,
                "description": a.description,
                "assignee_ids": [str(p.employee_id) for p in people],
                "due_at": due.isoformat() if due else None,
                "priority": a.priority,
            },
            "preview": {"title": "План — проверьте перед выполнением", "fields": fields},
            "steps": [
                {"text": f"Проверил права: можно создавать в «{project.name}»", "state": "done"},
                {
                    "text": "Создаю задачу"
                    + (f" и назначаю {people[0].full_name}" if people else ""),
                    "state": "wait",
                },
                {"text": "Добавлю наблюдателей и срок", "state": "wait"},
            ],
        }
    }


async def _apply_task_patch(
    ctx: ToolContext, task: Task, a: UpdateTaskArgs | UpdateTasksArgs
) -> dict[str, Any]:
    """Собрать тело TaskUpdate из аргументов модели (общее для одиночной и
    массовой правки). Резолв исполнителей — здесь же, чтобы неоднозначное имя
    всплыло ДО записи."""
    patch: dict[str, Any] = {}
    if getattr(a, "title", None) is not None:
        patch["title"] = a.title
    if a.status is not None:
        patch["status"] = a.status
    if a.priority is not None:
        patch["priority"] = a.priority
    if a.due_at is not None:
        patch["due_at"] = parse_due(a.due_at)
    if a.assignees is not None:
        people = await _resolve_assignees(ctx, a.assignees)
        patch["assignee_ids"] = [p.employee_id for p in people]
    return patch


async def t_update_task(ctx: ToolContext, a: UpdateTaskArgs) -> dict[str, Any]:
    """Правка ОДНОЙ задачи — выполняется сразу (порог подтверждения)."""
    from app.api.tasks import update_task as api_update_task
    from app.schemas.task import TaskUpdate

    task = await resolve_task(ctx, a.task)
    project = await ctx.db.get(Project, task.project_id)
    if not await can_edit_project(ctx, task.project_id):
        return denied(
            f"в проекте «{project.name if project else '—'}» у вас роль наблюдателя — "
            "менять задачи там нельзя",
            await project_managers(ctx, task.project_id),
        )
    patch = await _apply_task_patch(ctx, task, a)
    if not patch:
        return {"error": "Не указано, что менять"}
    updated = await api_update_task(
        task_id=task.id,
        body=TaskUpdate(**patch),
        principal=ctx.principal,
        db=ctx.db,
    )
    return {
        "done": True,
        "key": f"{project.key}-{updated.seq}" if project else str(updated.seq),
        "title": updated.title,
        "status": STATUS_RU[updated.status],
        "priority": PRIORITY_RU[updated.priority],
        "due": fmt_due(updated.due_at),
        "url": f"/projects/{updated.project_id}?task={updated.id}",
    }


async def t_update_tasks(ctx: ToolContext, a: UpdateTasksArgs) -> dict[str, Any]:
    """Массовая правка — всегда через план (затрагивает > 1 объекта)."""
    tasks: list[tuple[Task, Project | None]] = []
    for ref in a.tasks:
        task = await resolve_task(ctx, ref)
        tasks.append((task, await ctx.db.get(Project, task.project_id)))
    for task, project in tasks:
        if not await can_edit_project(ctx, task.project_id):
            return denied(
                f"в проекте «{project.name if project else '—'}» у вас роль наблюдателя",
                await project_managers(ctx, task.project_id),
            )
    patch = await _apply_task_patch(ctx, tasks[0][0], a)
    if not patch:
        return {"error": "Не указано, что менять"}
    keys = [f"{p.key}-{t.seq}" if p else str(t.seq) for t, p in tasks]
    changes = []
    if a.status:
        changes.append({"label": "Статус", "value": STATUS_RU[a.status]})
    if a.priority:
        changes.append(
            {"label": "Приоритет", "value": PRIORITY_RU[a.priority], "chip": "priority",
             "chip_text": a.priority}
        )
    if a.due_at:
        changes.append({"label": "Срок", "value": fmt_due(parse_due(a.due_at))})
    if a.assignees is not None:
        changes.append({"label": "Исполнители", "value": ", ".join(a.assignees), "chip": "who"})
    return {
        "__plan__": {
            "tool": "update_tasks",
            "scope": f"изменение задач · {len(tasks)} объекта",
            "args": {
                "task_ids": [str(t.id) for t, _ in tasks],
                "patch": {
                    k: (v.isoformat() if isinstance(v, datetime) else
                        [str(x) for x in v] if isinstance(v, list) else v)
                    for k, v in patch.items()
                },
            },
            "preview": {
                "title": "План — проверьте перед выполнением",
                "fields": [{"label": "Задачи", "value": ", ".join(keys)}, *changes],
            },
            "steps": [
                {"text": f"Проверил права на все {len(tasks)} задачи", "state": "done"},
                {"text": "Применю изменения одним пакетом", "state": "wait"},
            ],
        }
    }


async def t_archive_task(ctx: ToolContext, a: TaskRefArgs) -> dict[str, Any]:
    task = await resolve_task(ctx, a.task)
    project = await ctx.db.get(Project, task.project_id)
    if not await can_edit_project(ctx, task.project_id):
        return denied(
            f"в проекте «{project.name if project else '—'}» у вас роль наблюдателя",
            await project_managers(ctx, task.project_id),
        )
    key = f"{project.key}-{task.seq}" if project else str(task.seq)
    return {
        "__plan__": {
            "tool": "archive_task",
            "scope": "архивация задачи · 1 объект",
            "args": {"task_id": str(task.id)},
            "preview": {
                "title": "План — проверьте перед выполнением",
                "fields": [
                    {"label": "Задача", "value": f"{key} · {task.title}"},
                    {"label": "Действие", "value": "Перенести в архив"},
                ],
            },
            "steps": [
                {"text": "Проверил права на задачу", "state": "done"},
                {"text": "Перенесу в архив — вернуть можно из трекера", "state": "wait"},
            ],
        }
    }


async def t_add_comment(ctx: ToolContext, a: CommentArgs) -> dict[str, Any]:
    task = await resolve_task(ctx, a.task)
    project = await ctx.db.get(Project, task.project_id)
    key = f"{project.key}-{task.seq}" if project else str(task.seq)
    return {
        "__plan__": {
            "tool": "add_comment",
            "scope": "комментарий · 1 объект",
            "args": {"task_id": str(task.id), "text": a.text},
            "preview": {
                "title": "План — проверьте перед выполнением",
                "fields": [
                    {"label": "Задача", "value": f"{key} · {task.title}"},
                    {"label": "Комментарий", "value": a.text},
                ],
            },
            "steps": [
                {"text": "Нашёл задачу", "state": "done"},
                {"text": "Добавлю комментарий от вашего имени", "state": "wait"},
            ],
        }
    }


# ─── Реестр ─────────────────────────────────────────────────────────────────


@dataclass
class Tool:
    name: str
    description: str
    args_model: type[BaseModel]
    handler: Callable[[ToolContext, Any], Awaitable[dict[str, Any]]]
    kind: Literal["read", "write"]


class _NoArgs(BaseModel):
    pass


TOOLS: list[Tool] = [
    Tool("search_tasks", "Найти задачи трекера по фильтрам: проект, исполнитель, "
         "статус, приоритет, просроченность, слова из заголовка.",
         SearchTasksArgs, t_search_tasks, "read"),
    Tool("get_task", "Подробности одной задачи по номеру вида UPPETITTV-207.",
         TaskRefArgs, t_get_task, "read"),
    Tool("project_summary", "Сводка по проекту: сколько задач в каких статусах, "
         "просрочка, без исполнителя, движение за неделю.",
         ProjectRefArgs, t_project_summary, "read"),
    Tool("my_tasks", "Задачи, назначенные на спрашивающего.", MyTasksArgs, t_my_tasks, "read"),
    Tool("list_projects", "Проекты, доступные спрашивающему, и может ли он в них писать.",
         _NoArgs, t_list_projects, "read"),
    Tool("find_people", "Найти сотрудников по части имени.", FindPeopleArgs,
         t_find_people, "read"),
    Tool("search_knowledge", "Ответ по базе знаний: регламенты, стандарты, учебные "
         "материалы и карточки товаров.", KnowledgeArgs, t_search_knowledge, "read"),
    Tool("create_task", "Создать задачу. Требует подтверждения человеком.",
         CreateTaskArgs, t_create_task, "write"),
    Tool("update_task", "Изменить ОДНУ задачу: статус, срок, приоритет, исполнителей, "
         "заголовок. Выполняется сразу.", UpdateTaskArgs, t_update_task, "write"),
    Tool("update_tasks", "Изменить несколько задач одинаково. Требует подтверждения.",
         UpdateTasksArgs, t_update_tasks, "write"),
    Tool("archive_task", "Перенести задачу в архив. Требует подтверждения.",
         TaskRefArgs, t_archive_task, "write"),
    Tool("add_comment", "Добавить комментарий к задаче. Требует подтверждения.",
         CommentArgs, t_add_comment, "write"),
]

BY_NAME: dict[str, Tool] = {t.name: t for t in TOOLS}

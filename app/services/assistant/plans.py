"""Планы действий: создание, правка полей и исполнение.

Что здесь важно и проверяется тестами:

- **Права перепроверяются на ИСПОЛНЕНИИ.** Между показом карточки и нажатием
  «Выполнить» проходит время, за которое сотрудника могли вывести из
  проекта. Исполнители зовут те же ручки API, что и человек в трекере, —
  то есть `require_project_role` отработает заново сам.
- **Исполняются `args` из БД, а не тело запроса.** Клиент присылает только
  id плана; «Изменить поля» правит ограниченный whitelist и проходит ту же
  валидацию, что при создании.
- **Ровно один раз.** `pending → done` под `SELECT … FOR UPDATE`: два
  нажатия «Выполнить» не создадут две задачи.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, Field
from signaris_auth import Principal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai import AiPlan
from app.services.assistant.context import ToolContext
from app.services.audit import record as audit_record

# План живёт полчаса: за это время мир вокруг него ещё узнаваем. Права всё
# равно перепроверяются, но исполнять вчерашнее предложение бессмысленно.
PLAN_TTL = timedelta(minutes=30)


class PlanError(Exception):
    """Понятный сотруднику отказ (мапится в 409)."""


def create(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    employee_id: UUID,
    proposal: dict[str, Any],
) -> AiPlan:
    plan = AiPlan(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        employee_id=employee_id,
        tool=proposal["tool"],
        args=proposal["args"],
        preview={**proposal["preview"], "scope": proposal.get("scope", "")},
        steps=proposal.get("steps", []),
        status="pending",
        expires_at=datetime.now(UTC) + PLAN_TTL,
    )
    db.add(plan)
    return plan


def serialize(plan: AiPlan) -> dict[str, Any]:
    return {
        "id": str(plan.id),
        "tool": plan.tool,
        "scope": plan.preview.get("scope", ""),
        "title": plan.preview.get("title", "План — проверьте перед выполнением"),
        "fields": plan.preview.get("fields", []),
        "steps": plan.steps,
        "status": plan.status,
        "result": plan.result,
        "error": plan.error,
        "expires_at": plan.expires_at.isoformat(),
    }


async def load_for_actor(
    db: AsyncSession, plan_id: UUID, principal: Principal, *, lock: bool = False
) -> AiPlan:
    stmt = select(AiPlan).where(AiPlan.id == plan_id)
    if lock:
        stmt = stmt.with_for_update()
    plan = (await db.execute(stmt)).scalar_one_or_none()
    # Чужой план прячем как отсутствующий: подтверждать существование
    # действия, к которому нет доступа, незачем.
    if plan is None or plan.employee_id != principal.employee_id:
        raise HTTPException(status_code=404, detail="План не найден")
    return plan


# ─── Исполнители ────────────────────────────────────────────────────────────


async def _exec_create_task(
    db: AsyncSession, principal: Principal, args: dict[str, Any]
) -> dict[str, Any]:
    from app.api.tasks import create_task as api_create_task
    from app.models.project import Project
    from app.schemas.task import TaskCreate

    project_id = UUID(args["project_id"])
    due = args.get("due_at")
    created = await api_create_task(
        project_id=project_id,
        body=TaskCreate(
            title=args["title"],
            description=args.get("description"),
            priority=args.get("priority", "medium"),
            assignee_ids=[UUID(i) for i in args.get("assignee_ids", [])] or None,
            due_at=datetime.fromisoformat(due) if due else None,
        ),
        principal=principal,
        db=db,
    )
    project = await db.get(Project, project_id)
    key = f"{project.key}-{created.seq}" if project else str(created.seq)
    return {
        "text": f"Создана {key}",
        "url": f"/projects/{project_id}?task={created.id}",
        "link_text": "Открыть задачу →",
    }


async def _exec_update_tasks(
    db: AsyncSession, principal: Principal, args: dict[str, Any]
) -> dict[str, Any]:
    from app.api.tasks import update_task as api_update_task
    from app.schemas.task import TaskUpdate

    raw = dict(args["patch"])
    if raw.get("due_at"):
        raw["due_at"] = datetime.fromisoformat(raw["due_at"])
    if raw.get("assignee_ids") is not None:
        raw["assignee_ids"] = [UUID(i) for i in raw["assignee_ids"]]
    ids = [UUID(i) for i in args["task_ids"]]
    for task_id in ids:
        await api_update_task(
            task_id=task_id, body=TaskUpdate(**raw), principal=principal, db=db
        )
    return {"text": f"Изменено задач: {len(ids)}"}


async def _exec_archive_task(
    db: AsyncSession, principal: Principal, args: dict[str, Any]
) -> dict[str, Any]:
    from app.api.tasks import archive_task as api_archive_task

    task_id = UUID(args["task_id"])
    await api_archive_task(task_id=task_id, principal=principal, db=db)
    return {"text": "Задача перенесена в архив"}


async def _exec_add_comment(
    db: AsyncSession, principal: Principal, args: dict[str, Any]
) -> dict[str, Any]:
    from app.api.comments import create_comment as api_create_comment
    from app.schemas.comment import CommentCreate

    task_id = UUID(args["task_id"])
    await api_create_comment(
        task_id=task_id,
        body=CommentCreate(body=args["text"]),
        principal=principal,
        db=db,
    )
    return {
        "text": "Комментарий добавлен",
        "url": f"/tasks/{task_id}",
        "link_text": "Открыть задачу →",
    }


EXECUTORS = {
    "create_task": _exec_create_task,
    "update_tasks": _exec_update_tasks,
    "archive_task": _exec_archive_task,
    "add_comment": _exec_add_comment,
}


async def execute(db: AsyncSession, plan: AiPlan, principal: Principal) -> AiPlan:
    """Исполнить план. Права проверяют сами ручки API — того же уровня,
    что и для человека в интерфейсе."""
    if plan.status != "pending":
        raise PlanError(
            "Этот план уже выполнен" if plan.status == "done" else "Этот план больше не активен"
        )
    if plan.expires_at < datetime.now(UTC):
        plan.status = "failed"
        plan.error = "Срок действия плана истёк"
        await db.commit()
        raise PlanError("Прошло больше получаса — соберите план заново, данные могли измениться")

    executor = EXECUTORS.get(plan.tool)
    if executor is None:
        raise PlanError(f"Не умею выполнять «{plan.tool}»")

    # Снимаем всё нужное ДО исполнения: rollback ниже протухает атрибуты, и
    # обращение к plan.id уже потребовало бы IO в синхронном контексте
    # (MissingGreenlet). Ловилось тестом на перепроверку прав.
    plan_id, tenant_id, tool = plan.id, plan.tenant_id, plan.tool

    try:
        result = await executor(db, principal, plan.args)
    except HTTPException as e:
        # Ручка API откатила транзакцию — отметку о провале пишем заново,
        # перечитав план.
        detail = str(e.detail)
        await db.rollback()
        fresh = await db.get(AiPlan, plan_id)
        if fresh is not None and fresh.status == "pending":
            fresh.status = "failed"
            fresh.error = detail[:500]
            await db.commit()
        raise PlanError(f"Не удалось выполнить: {detail}") from None

    # Ручка API уже закоммитила своё — план перечитываем из свежей
    # транзакции, иначе пишем в протухший объект.
    fresh = await db.get(AiPlan, plan_id)
    if fresh is None:  # pragma: no cover — диалог удалили в параллель
        raise PlanError("План исчез, пока выполнялся")
    fresh.status = "done"
    fresh.result = result
    fresh.executed_at = datetime.now(UTC)
    audit_record(
        db,
        tenant_id=tenant_id,
        actor_id=principal.employee_id,
        action="assistant.execute",
        object_type="ai_plan",
        object_id=plan_id,
        object_label=tool,
        diff={"tool": {"old": None, "new": tool}},
    )
    await db.commit()
    return fresh


# ─── «Изменить поля» ────────────────────────────────────────────────────────


class PlanPatch(BaseModel):
    """Whitelist правки карточки. Проект и набор задач НЕ меняются: это
    сменило бы объект действия, а не его параметры, — такое честнее
    попросить заново словами."""

    title: str | None = Field(default=None, min_length=1, max_length=500)
    due_at: str | None = None
    priority: Literal["low", "medium", "high", "urgent"] | None = None
    assignees: list[str] | None = Field(default=None, max_length=10)
    text: str | None = Field(default=None, min_length=1, max_length=4000)
    # Явная очистка срока: отличаем «не трогали» от «убрать».
    clear_due: bool = False


async def rebuild_preview(ctx: ToolContext, plan: AiPlan) -> None:
    """Пересобрать карточку ИЗ args — то есть из того, что реально
    исполнится. Иначе после правки полей человек подтверждал бы одно, а
    выполнялось другое."""
    from app.models.project import Project
    from app.models.shadow import ShadowUser
    from app.services.assistant.tools import PRIORITY_RU, fmt_due

    args = plan.args
    fields: list[dict[str, Any]] = []
    if plan.tool == "create_task":
        project = await ctx.db.get(Project, UUID(args["project_id"]))
        fields.append(
            {
                "label": "Проект",
                "value": project.name if project else "—",
                "chip": "key",
                "chip_text": project.key if project else "",
            }
        )
        fields.append({"label": "Заголовок", "value": args["title"]})
        ids = [UUID(i) for i in args.get("assignee_ids", [])]
        if ids:
            people = (
                (
                    await ctx.db.execute(
                        select(ShadowUser).where(ShadowUser.employee_id.in_(ids))
                    )
                )
                .scalars()
                .all()
            )
            fields.append(
                {
                    "label": "Исполнитель" if len(people) == 1 else "Исполнители",
                    "value": ", ".join(p.full_name or "—" for p in people),
                    "chip": "who",
                }
            )
        if args.get("due_at"):
            fields.append(
                {"label": "Срок", "value": fmt_due(datetime.fromisoformat(args["due_at"]))}
            )
        prio = args.get("priority", "medium")
        fields.append(
            {
                "label": "Приоритет",
                "value": PRIORITY_RU[prio],
                "chip": "priority",
                "chip_text": prio,
            }
        )
    elif plan.tool == "add_comment":
        fields = [f for f in plan.preview.get("fields", []) if f["label"] != "Комментарий"]
        fields.append({"label": "Комментарий", "value": args["text"]})
    else:
        fields = plan.preview.get("fields", [])
    plan.preview = {**plan.preview, "fields": fields}


async def apply_patch(ctx: ToolContext, plan: AiPlan, patch: PlanPatch) -> AiPlan:
    from app.services.assistant.tools import _resolve_assignees, parse_due

    if plan.status != "pending":
        raise PlanError("План уже нельзя менять")

    args = dict(plan.args)
    if plan.tool == "create_task":
        if patch.title is not None:
            args["title"] = patch.title
        if patch.priority is not None:
            args["priority"] = patch.priority
        if patch.clear_due:
            args["due_at"] = None
        elif patch.due_at is not None:
            due = parse_due(patch.due_at)
            args["due_at"] = due.isoformat() if due else None
        if patch.assignees is not None:
            people = await _resolve_assignees(ctx, patch.assignees)
            args["assignee_ids"] = [str(p.employee_id) for p in people]
    elif plan.tool == "add_comment" and patch.text is not None:
        args["text"] = patch.text
    elif plan.tool == "update_tasks":
        inner = dict(args.get("patch", {}))
        if patch.priority is not None:
            inner["priority"] = patch.priority
        if patch.clear_due:
            inner["due_at"] = None
        elif patch.due_at is not None:
            due = parse_due(patch.due_at)
            inner["due_at"] = due.isoformat() if due else None
        args["patch"] = inner
    else:
        raise PlanError("У этого плана нечего править — попросите заново словами")

    plan.args = args
    # Продлеваем срок: человек только что подтвердил, что помнит контекст.
    plan.expires_at = datetime.now(UTC) + PLAN_TTL
    await rebuild_preview(ctx, plan)
    await ctx.db.commit()
    return plan

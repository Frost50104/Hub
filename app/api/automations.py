"""Автосценарии API (Ф5, ТЗ §22) — управление welcome-правилами (hub-admin).

Правка правила НЕ трогает уже материализованные jobs (инвариант плана);
applies_from фиксируется при создании — ретро-применения к старым
профилям нет.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from signaris_auth import Principal
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db, require_auth
from app.models.automation import AutomationJob, AutomationRule
from app.models.course import Course
from app.models.employee_profile import EmployeeProfile
from app.services import audit

router = APIRouter(tags=["learn-automations"])

_ADMIN = require_auth(roles=["admin"])


class RuleUpsert(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    trigger: str = Field(pattern="^(profile_activated|position_assigned)$")
    position_ids: list[UUID] = Field(default_factory=list, max_length=50)
    course_id: UUID
    due_days: int | None = Field(default=None, ge=1, le=365)
    enabled: bool = True


class RuleResponse(BaseModel):
    id: UUID
    title: str
    trigger: str
    position_ids: list[UUID]
    course_id: UUID
    course_title: str | None = None
    due_days: int | None
    enabled: bool
    applies_from: datetime
    jobs_pending: int = 0
    jobs_done: int = 0


class JobResponse(BaseModel):
    id: UUID
    profile_id: UUID
    employee_name: str | None = None
    status: str
    due_at: datetime | None
    created_at: datetime
    executed_at: datetime | None


async def _rule_or_404(db: AsyncSession, rule_id: UUID) -> AutomationRule:
    rule = await db.get(AutomationRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Правило не найдено")
    return rule


def _to_response(
    rule: AutomationRule,
    course_titles: dict[UUID, str],
    counters: dict[UUID, dict[str, int]],
) -> RuleResponse:
    counts = counters.get(rule.id, {})
    return RuleResponse(
        id=rule.id,
        title=rule.title,
        trigger=rule.trigger,
        position_ids=list(rule.position_ids or []),
        course_id=rule.course_id,
        course_title=course_titles.get(rule.course_id),
        due_days=rule.due_days,
        enabled=rule.enabled,
        applies_from=rule.applies_from,
        jobs_pending=counts.get("pending", 0),
        jobs_done=counts.get("done", 0),
    )


async def _load_context(
    db: AsyncSession, rules: list[AutomationRule]
) -> tuple[dict[UUID, str], dict[UUID, dict[str, int]]]:
    course_titles: dict[UUID, str] = {}
    counters: dict[UUID, dict[str, int]] = {}
    if rules:
        for cid, title in await db.execute(
            select(Course.id, Course.title).where(
                Course.id.in_({r.course_id for r in rules})
            )
        ):
            course_titles[cid] = title
        for rid, job_status, count in await db.execute(
            select(AutomationJob.rule_id, AutomationJob.status, func.count())
            .where(AutomationJob.rule_id.in_([r.id for r in rules]))
            .group_by(AutomationJob.rule_id, AutomationJob.status)
        ):
            counters.setdefault(rid, {})[job_status] = count
    return course_titles, counters


@router.get("/learn/automations", response_model=list[RuleResponse])
async def list_rules(
    principal: Principal = Depends(_ADMIN),
    db: AsyncSession = Depends(get_db),
) -> list[RuleResponse]:
    rules = (
        (await db.execute(select(AutomationRule).order_by(AutomationRule.created_at)))
        .scalars()
        .all()
    )
    course_titles, counters = await _load_context(db, list(rules))
    return [_to_response(r, course_titles, counters) for r in rules]


@router.post("/learn/automations", response_model=RuleResponse, status_code=201)
async def create_rule(
    body: RuleUpsert,
    principal: Principal = Depends(_ADMIN),
    db: AsyncSession = Depends(get_db),
) -> RuleResponse:
    course = await db.get(Course, body.course_id)
    if course is None:
        raise HTTPException(status_code=422, detail="Курс не найден")
    rule = AutomationRule(
        tenant_id=principal.tenant_id,
        title=body.title,
        trigger=body.trigger,
        position_ids=body.position_ids,
        course_id=body.course_id,
        due_days=body.due_days,
        enabled=body.enabled,
        created_by=principal.employee_id,
    )
    db.add(rule)
    await db.flush()
    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor_id=principal.employee_id,
        action="create",
        object_type="automation_rule",
        object_id=rule.id,
        object_label=rule.title,
    )
    await db.commit()
    await db.refresh(rule)
    course_titles, counters = await _load_context(db, [rule])
    return _to_response(rule, course_titles, counters)


@router.patch("/learn/automations/{rule_id}", response_model=RuleResponse)
async def update_rule(
    rule_id: UUID,
    body: RuleUpsert,
    principal: Principal = Depends(_ADMIN),
    db: AsyncSession = Depends(get_db),
) -> RuleResponse:
    rule = await _rule_or_404(db, rule_id)
    rule.title = body.title
    rule.trigger = body.trigger
    rule.position_ids = body.position_ids
    rule.course_id = body.course_id
    rule.due_days = body.due_days
    rule.enabled = body.enabled
    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor_id=principal.employee_id,
        action="update",
        object_type="automation_rule",
        object_id=rule.id,
        object_label=rule.title,
    )
    await db.commit()
    await db.refresh(rule)
    course_titles, counters = await _load_context(db, [rule])
    return _to_response(rule, course_titles, counters)


@router.delete("/learn/automations/{rule_id}", status_code=204)
async def delete_rule(
    rule_id: UUID,
    principal: Principal = Depends(_ADMIN),
    db: AsyncSession = Depends(get_db),
) -> None:
    rule = await _rule_or_404(db, rule_id)
    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor_id=principal.employee_id,
        action="delete",
        object_type="automation_rule",
        object_id=rule.id,
        object_label=rule.title,
    )
    await db.delete(rule)  # jobs каскадом; выданные назначения остаются
    await db.commit()


@router.get("/learn/automations/{rule_id}/jobs", response_model=list[JobResponse])
async def rule_jobs(
    rule_id: UUID,
    principal: Principal = Depends(_ADMIN),
    db: AsyncSession = Depends(get_db),
) -> list[JobResponse]:
    await _rule_or_404(db, rule_id)
    rows = (
        await db.execute(
            select(AutomationJob, EmployeeProfile.full_name)
            .join(EmployeeProfile, EmployeeProfile.id == AutomationJob.profile_id)
            .where(AutomationJob.rule_id == rule_id)
            .order_by(AutomationJob.created_at.desc())
            .limit(200)
        )
    ).all()
    return [
        JobResponse(
            id=j.id,
            profile_id=j.profile_id,
            employee_name=name,
            status=j.status,
            due_at=j.due_at,
            created_at=j.created_at,
            executed_at=j.executed_at,
        )
        for j, name in rows
    ]


@router.post("/learn/automation-jobs/{job_id}/cancel", status_code=204)
async def cancel_job(
    job_id: UUID,
    principal: Principal = Depends(_ADMIN),
    db: AsyncSession = Depends(get_db),
) -> None:
    job = await db.get(AutomationJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Задание не найдено")
    if job.status != "pending":
        raise HTTPException(status_code=409, detail="Отменить можно только ожидающее")
    job.status = "cancelled"
    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor_id=principal.employee_id,
        action="update",
        object_type="automation_job",
        object_id=job.id,
        object_label="cancel",
    )
    await db.commit()

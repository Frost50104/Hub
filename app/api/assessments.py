"""Аттестации API (Ф8, ТЗ §20).

Кампания = свой quiz (движок Ф3b: попытки, снапшоты, ревью открытых
вопросов). Управление — publisher/hub-admin; сотрудник видит active-кампании
своей аудитории в окне дат и проходит их существующими квиз-ручками.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from signaris_auth import Principal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.quizzes import _manage_response, consumer_quiz_state
from app.deps import get_db, require_auth
from app.models.assessment import AssessmentCampaign
from app.models.audience import AudienceMember
from app.models.employee_profile import EmployeeProfile
from app.models.quiz import Quiz, QuizAttempt, QuizQuestion
from app.schemas.library import AudienceBody
from app.schemas.quiz import (
    QuizConsumerResponse,
    QuizManageResponse,
    QuizUpsert,
)
from app.services import audit, lifecycle
from app.services.audience_resolver import RuleSpec, set_object_audience
from app.services.content_access import require_content_role, resolve_content_role
from app.services.learn_notify import _employee_ids
from app.services.notify_batch import notify_many
from app.services.org_scope import get_profile, resolve_scope

router = APIRouter(tags=["learn-assessments"])


class CampaignUpsert(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    starts_at: datetime | None = None
    ends_at: datetime | None = None


class CampaignView(BaseModel):
    id: UUID
    title: str
    description: str | None
    audience_id: UUID | None
    starts_at: datetime | None
    ends_at: datetime | None
    status: str
    quiz_id: UUID | None = None
    question_count: int = 0
    created_at: datetime
    # Сотруднику:
    my_state: QuizConsumerResponse | None = None
    # Менеджеру:
    audience_size: int = 0
    completed_count: int = 0


class ImportBody(BaseModel):
    quiz_id: UUID


class ReportRow(BaseModel):
    profile_id: UUID
    full_name: str
    status: str  # not_started | in_progress | pending_review | passed | failed
    score_pct: int | None
    finished_at: datetime | None


class ReportResponse(BaseModel):
    campaign_id: UUID
    title: str
    rows: list[ReportRow]


def _rule_specs(body: AudienceBody) -> list[RuleSpec]:
    return [
        RuleSpec(
            mode=r.mode,
            profile_ids=frozenset(r.profile_ids),
            position_ids=frozenset(r.position_ids),
            position_group_ids=frozenset(r.position_group_ids),
            store_ids=frozenset(r.store_ids),
            store_group_ids=frozenset(r.store_group_ids),
            franchisee_ids=frozenset(r.franchisee_ids),
            franchisee_group_ids=frozenset(r.franchisee_group_ids),
            department_ids=frozenset(r.department_ids),
            user_group_ids=frozenset(r.user_group_ids),
        )
        for r in body.rules
    ]


async def _campaign_or_404(db: AsyncSession, campaign_id: UUID) -> AssessmentCampaign:
    campaign = await db.get(AssessmentCampaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Аттестация не найдена")
    return campaign


async def _campaign_quiz(db: AsyncSession, campaign_id: UUID) -> Quiz | None:
    return (
        await db.execute(select(Quiz).where(Quiz.campaign_id == campaign_id))
    ).scalar_one_or_none()


async def _audience_profile_ids(
    db: AsyncSession, audience_id: UUID | None
) -> list[UUID]:
    if audience_id is None:
        rows = await db.execute(
            select(EmployeeProfile.id).where(EmployeeProfile.status == "active")
        )
    else:
        rows = await db.execute(
            select(AudienceMember.profile_id).where(
                AudienceMember.audience_id == audience_id
            )
        )
    return [r[0] for r in rows]


def _in_window(campaign: AssessmentCampaign, now: datetime) -> bool:
    if campaign.starts_at is not None and campaign.starts_at > now:
        return False
    return not (campaign.ends_at is not None and campaign.ends_at <= now)


# ─── Списки ──────────────────────────────────────────────────────────────────


@router.get("/learn/assessments", response_model=list[CampaignView])
async def list_campaigns(
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> list[CampaignView]:
    role = await resolve_content_role(db, principal)
    profile = await get_profile(db, principal)
    is_manager = lifecycle.can(role, "publisher")
    now = datetime.now(UTC)

    if is_manager:
        campaigns = (
            (
                await db.execute(
                    select(AssessmentCampaign).order_by(
                        AssessmentCampaign.created_at.desc()
                    )
                )
            )
            .scalars()
            .all()
        )
    else:
        if profile is None:
            return []
        member_of = select(AudienceMember.audience_id).where(
            AudienceMember.profile_id == profile.id
        )
        campaigns = [
            c
            for c in (
                await db.execute(
                    select(AssessmentCampaign).where(
                        AssessmentCampaign.status == "active",
                        (AssessmentCampaign.audience_id.is_(None))
                        | AssessmentCampaign.audience_id.in_(member_of),
                    )
                )
            )
            .scalars()
            .all()
            if _in_window(c, now)
        ]

    out = []
    for campaign in campaigns:
        quiz = await _campaign_quiz(db, campaign.id)
        question_count = 0
        my_state = None
        audience_size = completed_count = 0
        if quiz is not None:
            question_count = (
                await db.execute(
                    select(QuizQuestion.id).where(QuizQuestion.quiz_id == quiz.id)
                )
            ).scalars().all()
            question_count = len(question_count)
            if not is_manager and profile is not None:
                my_state = await consumer_quiz_state(db, quiz, profile)
            if is_manager:
                members = await _audience_profile_ids(db, campaign.audience_id)
                audience_size = len(members)
                finished = {
                    r[0]
                    for r in await db.execute(
                        select(QuizAttempt.profile_id).where(
                            QuizAttempt.quiz_id == quiz.id,
                            QuizAttempt.finished_at.is_not(None),
                        )
                    )
                }
                completed_count = len(finished & set(members))
        out.append(
            CampaignView(
                id=campaign.id,
                title=campaign.title,
                description=campaign.description,
                audience_id=campaign.audience_id,
                starts_at=campaign.starts_at,
                ends_at=campaign.ends_at,
                status=campaign.status,
                quiz_id=quiz.id if quiz else None,
                question_count=question_count,
                created_at=campaign.created_at,
                my_state=my_state,
                audience_size=audience_size,
                completed_count=completed_count,
            )
        )
    return out


# ─── Управление ──────────────────────────────────────────────────────────────


@router.post("/learn/assessments", response_model=CampaignView, status_code=201)
async def create_campaign(
    body: CampaignUpsert,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> CampaignView:
    await require_content_role(db, principal, "publisher")
    campaign = AssessmentCampaign(
        tenant_id=principal.tenant_id,
        title=body.title,
        description=body.description,
        starts_at=body.starts_at,
        ends_at=body.ends_at,
        created_by=principal.employee_id,
    )
    db.add(campaign)
    await db.flush()
    quiz = Quiz(
        tenant_id=principal.tenant_id,
        campaign_id=campaign.id,
        title=body.title,
        attempts_limit=1,
        is_required=False,
        shuffle_questions=True,
        created_by=principal.employee_id,
    )
    db.add(quiz)
    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor_id=principal.employee_id,
        action="create",
        object_type="assessment_campaign",
        object_id=campaign.id,
        object_label=campaign.title,
    )
    await db.commit()
    await db.refresh(campaign)
    return CampaignView(
        id=campaign.id,
        title=campaign.title,
        description=campaign.description,
        audience_id=campaign.audience_id,
        starts_at=campaign.starts_at,
        ends_at=campaign.ends_at,
        status=campaign.status,
        quiz_id=quiz.id,
        created_at=campaign.created_at,
    )


@router.patch("/learn/assessments/{campaign_id}", response_model=CampaignView)
async def update_campaign(
    campaign_id: UUID,
    body: CampaignUpsert,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> CampaignView:
    await require_content_role(db, principal, "publisher")
    campaign = await _campaign_or_404(db, campaign_id)
    campaign.title = body.title
    campaign.description = body.description
    campaign.starts_at = body.starts_at
    campaign.ends_at = body.ends_at
    await db.commit()
    await db.refresh(campaign)
    quiz = await _campaign_quiz(db, campaign_id)
    return CampaignView(
        id=campaign.id,
        title=campaign.title,
        description=campaign.description,
        audience_id=campaign.audience_id,
        starts_at=campaign.starts_at,
        ends_at=campaign.ends_at,
        status=campaign.status,
        quiz_id=quiz.id if quiz else None,
        created_at=campaign.created_at,
    )


@router.put("/learn/assessments/{campaign_id}/audience", status_code=204)
async def set_campaign_audience(
    campaign_id: UUID,
    body: AudienceBody,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> None:
    await require_content_role(db, principal, "publisher")
    campaign = await _campaign_or_404(db, campaign_id)
    try:
        audience_id, _diff = await set_object_audience(
            db,
            tenant_id=principal.tenant_id,
            current_audience_id=campaign.audience_id,
            is_all=body.is_all,
            rules=_rule_specs(body),
            object_hint=f"assessment:{campaign.id}",
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    campaign.audience_id = audience_id
    await db.commit()


@router.get("/learn/assessments/{campaign_id}/quiz", response_model=QuizManageResponse)
async def get_campaign_quiz(
    campaign_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> QuizManageResponse:
    await require_content_role(db, principal, "publisher")
    await _campaign_or_404(db, campaign_id)
    quiz = await _campaign_quiz(db, campaign_id)
    if quiz is None:
        raise HTTPException(status_code=404, detail="Квиз кампании не найден")
    return await _manage_response(db, quiz)


@router.put("/learn/assessments/{campaign_id}/quiz", response_model=QuizManageResponse)
async def upsert_campaign_quiz(
    campaign_id: UUID,
    body: QuizUpsert,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> QuizManageResponse:
    """Настройки и вопросы квиза кампании (replace, как у тестов уроков)."""
    from sqlalchemy import delete

    await require_content_role(db, principal, "publisher")
    await _campaign_or_404(db, campaign_id)
    quiz = await _campaign_quiz(db, campaign_id)
    if quiz is None:
        raise HTTPException(status_code=404, detail="Квиз кампании не найден")

    quiz.title = body.title
    quiz.description = body.description
    quiz.status = body.status
    quiz.pass_score_pct = body.pass_score_pct
    quiz.attempts_limit = body.attempts_limit
    quiz.shuffle_questions = body.shuffle_questions
    quiz.shuffle_options = body.shuffle_options
    quiz.show_correct_answers = body.show_correct_answers
    quiz.is_required = body.is_required
    await db.execute(delete(QuizQuestion).where(QuizQuestion.quiz_id == quiz.id))
    for i, draft in enumerate(body.questions):
        db.add(
            QuizQuestion(
                tenant_id=quiz.tenant_id,
                quiz_id=quiz.id,
                position=i,
                qtype=draft.qtype,
                prompt=draft.prompt,
                media_id=draft.media_id,
                options=draft.options,
                answer=draft.answer,
                points=draft.points,
            )
        )
    await db.commit()
    return await _manage_response(db, quiz)


@router.post(
    "/learn/assessments/{campaign_id}/import-questions",
    response_model=QuizManageResponse,
)
async def import_questions(
    campaign_id: UUID,
    body: ImportBody,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> QuizManageResponse:
    """Импорт вопросов из теста урока (копия в конец квиза кампании)."""
    await require_content_role(db, principal, "publisher")
    await _campaign_or_404(db, campaign_id)
    quiz = await _campaign_quiz(db, campaign_id)
    if quiz is None:
        raise HTTPException(status_code=404, detail="Квиз кампании не найден")
    source = await db.get(Quiz, body.quiz_id)
    if source is None or source.id == quiz.id:
        raise HTTPException(status_code=404, detail="Исходный тест не найден")

    max_pos = (
        await db.execute(
            select(QuizQuestion.position)
            .where(QuizQuestion.quiz_id == quiz.id)
            .order_by(QuizQuestion.position.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    next_pos = (max_pos if max_pos is not None else -1) + 1
    source_questions = (
        (
            await db.execute(
                select(QuizQuestion)
                .where(QuizQuestion.quiz_id == source.id)
                .order_by(QuizQuestion.position)
            )
        )
        .scalars()
        .all()
    )
    for question in source_questions:
        db.add(
            QuizQuestion(
                tenant_id=quiz.tenant_id,
                quiz_id=quiz.id,
                position=next_pos,
                qtype=question.qtype,
                prompt=question.prompt,
                media_id=question.media_id,
                options=question.options,
                answer=question.answer,
                points=question.points,
            )
        )
        next_pos += 1
    await db.commit()
    return await _manage_response(db, quiz)


@router.post("/learn/assessments/{campaign_id}/activate", status_code=204)
async def activate_campaign(
    campaign_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> None:
    await require_content_role(db, principal, "publisher")
    campaign = await _campaign_or_404(db, campaign_id)
    quiz = await _campaign_quiz(db, campaign_id)
    if quiz is None:
        raise HTTPException(status_code=404, detail="Квиз кампании не найден")
    has_questions = (
        await db.execute(
            select(QuizQuestion.id).where(QuizQuestion.quiz_id == quiz.id).limit(1)
        )
    ).scalar_one_or_none()
    if has_questions is None:
        raise HTTPException(status_code=422, detail="Добавьте вопросы аттестации")

    campaign.status = "active"
    quiz.status = "published"
    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor_id=principal.employee_id,
        action="publish",
        object_type="assessment_campaign",
        object_id=campaign.id,
        object_label=campaign.title,
    )
    members = await _audience_profile_ids(db, campaign.audience_id)
    recipients = await _employee_ids(db, members)
    deadline = (
        f" до {campaign.ends_at.astimezone(UTC).strftime('%d.%m.%Y')}"
        if campaign.ends_at
        else ""
    )
    await notify_many(
        db,
        tenant_id=campaign.tenant_id,
        employee_ids=list(recipients.values()),
        kind="assessment.assigned",
        title=campaign.title,
        body=f"Вам назначена аттестация{deadline} — пройдите тест.",
        url="/learn/assessments",
        payload={"campaign_id": str(campaign.id)},
    )
    await db.commit()


@router.post("/learn/assessments/{campaign_id}/close", status_code=204)
async def close_campaign(
    campaign_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> None:
    await require_content_role(db, principal, "publisher")
    campaign = await _campaign_or_404(db, campaign_id)
    campaign.status = "closed"
    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor_id=principal.employee_id,
        action="archive",
        object_type="assessment_campaign",
        object_id=campaign.id,
        object_label=campaign.title,
    )
    await db.commit()


@router.delete("/learn/assessments/{campaign_id}", status_code=204)
async def delete_campaign(
    campaign_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> None:
    await require_content_role(db, principal, "publisher")
    campaign = await _campaign_or_404(db, campaign_id)
    if campaign.status != "draft":
        raise HTTPException(
            status_code=409, detail="Активную/закрытую кампанию нельзя удалить"
        )
    await db.delete(campaign)  # квиз и попытки каскадом
    await db.commit()


@router.get("/learn/assessments/{campaign_id}/report", response_model=ReportResponse)
async def campaign_report(
    campaign_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> ReportResponse:
    """Отчёт: publisher — вся аудитория; ТУ/франчайзи — срез своих магазинов."""
    role = await resolve_content_role(db, principal)
    scope = await resolve_scope(db, principal)
    if not lifecycle.can(role, "publisher") and scope.kind != "stores":
        raise HTTPException(status_code=403, detail="Отчёт доступен руководителям")
    campaign = await _campaign_or_404(db, campaign_id)
    quiz = await _campaign_quiz(db, campaign_id)

    member_ids = await _audience_profile_ids(db, campaign.audience_id)
    profiles = (
        (
            await db.execute(
                select(EmployeeProfile)
                .where(EmployeeProfile.id.in_(member_ids or [UUID(int=0)]))
                .order_by(EmployeeProfile.full_name)
            )
        )
        .scalars()
        .all()
    )
    if not lifecycle.can(role, "publisher"):
        profiles = [p for p in profiles if p.store_id in (scope.store_ids or frozenset())]

    attempts_by_profile: dict[UUID, list[QuizAttempt]] = {}
    if quiz is not None:
        rows = (
            (
                await db.execute(
                    select(QuizAttempt).where(QuizAttempt.quiz_id == quiz.id)
                )
            )
            .scalars()
            .all()
        )
        for attempt in rows:
            attempts_by_profile.setdefault(attempt.profile_id, []).append(attempt)

    report_rows = []
    for profile in profiles:
        attempts = attempts_by_profile.get(profile.id, [])
        finished = [a for a in attempts if a.finished_at is not None]
        status = "not_started"
        score = None
        finished_at = None
        if any(a.finished_at is None for a in attempts):
            status = "in_progress"
        if finished:
            best = max(finished, key=lambda a: (a.score_pct or 0))
            score = best.score_pct
            finished_at = best.finished_at
            if any(a.needs_review and a.reviewed_at is None for a in finished):
                status = "pending_review"
            elif any(a.passed for a in finished):
                status = "passed"
            else:
                status = "failed"
        report_rows.append(
            ReportRow(
                profile_id=profile.id,
                full_name=profile.full_name,
                status=status,
                score_pct=score,
                finished_at=finished_at,
            )
        )
    return ReportResponse(campaign_id=campaign.id, title=campaign.title, rows=report_rows)

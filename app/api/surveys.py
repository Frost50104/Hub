"""Опросы API (Ф2, ТЗ §13).

Submit — одна транзакция: participation (ON CONFLICT → 409 повторное) +
answer_set с демографическим снапшотом (profile_id только у неанонимных,
без timestamp) + answers. Результаты — ТОЛЬКО через survey_stats
(k-anonymity, срез по одному измерению).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from signaris_auth import Principal
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import enforce_rate_limit, get_db, require_auth
from app.models.audience import AudienceMember
from app.models.employee_profile import EmployeeProfile
from app.models.survey import (
    Survey,
    SurveyAnswer,
    SurveyAnswerSet,
    SurveyParticipation,
    SurveyQuestion,
)
from app.schemas.library import AudienceBody
from app.schemas.survey import (
    QuestionResponse,
    QuestionsReplace,
    QuestionStatsResponse,
    SubmitBody,
    SurveyCreate,
    SurveyListResponse,
    SurveyResponse,
    SurveyResultsResponse,
    SurveyUpdate,
)
from app.services import audit, lifecycle
from app.services.audience_resolver import RuleSpec, set_object_audience, visible_filter
from app.services.content_access import require_content_role, resolve_content_role
from app.services.learn_notify import _employee_ids
from app.services.learn_settings import get_settings_dict
from app.services.notify_batch import notify_many
from app.services.org_scope import get_profile
from app.services.points import award
from app.services.survey_stats import participants_count, question_stats

router = APIRouter(tags=["learn-surveys"])

_OBJECT_TYPE = "survey"


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


def _is_open_now(survey: Survey, now: datetime) -> bool:
    if survey.status != "published":
        return False
    if survey.opens_at and now < survey.opens_at:
        return False
    return not (survey.closes_at and now >= survey.closes_at)


async def _get_survey_or_404(db: AsyncSession, survey_id: UUID) -> Survey:
    survey = await db.get(Survey, survey_id)
    if survey is None:
        raise HTTPException(status_code=404, detail="Опрос не найден")
    return survey


def _require_manage(survey: Survey, principal: Principal, role: lifecycle.ContentRole) -> None:
    if lifecycle.can(role, "publisher"):
        return
    if role == "author" and survey.created_by == principal.employee_id:
        return
    raise HTTPException(status_code=403, detail="Это не ваш опрос")


async def _survey_visible_to(
    db: AsyncSession, survey: Survey, profile_id: UUID | None
) -> bool:
    if survey.audience_id is None:
        return True
    if profile_id is None:
        return False
    row = await db.execute(
        select(AudienceMember.profile_id).where(
            AudienceMember.audience_id == survey.audience_id,
            AudienceMember.profile_id == profile_id,
        )
    )
    return row.scalar_one_or_none() is not None


async def _questions(db: AsyncSession, survey_id: UUID) -> list[SurveyQuestion]:
    return list(
        (
            await db.execute(
                select(SurveyQuestion)
                .where(SurveyQuestion.survey_id == survey_id)
                .order_by(SurveyQuestion.position)
            )
        )
        .scalars()
        .all()
    )


async def _to_response(
    db: AsyncSession,
    survey: Survey,
    *,
    profile_id: UUID | None,
    with_questions: bool = True,
    participated: bool | None = None,
) -> SurveyResponse:
    resp = SurveyResponse.model_validate(survey)
    if with_questions:
        resp.questions = [
            QuestionResponse.model_validate(q) for q in await _questions(db, survey.id)
        ]
    if participated is None and profile_id is not None:
        participated = (
            await db.execute(
                select(SurveyParticipation.profile_id).where(
                    SurveyParticipation.survey_id == survey.id,
                    SurveyParticipation.profile_id == profile_id,
                )
            )
        ).scalar_one_or_none() is not None
    resp.participated = bool(participated)
    resp.is_open_now = _is_open_now(survey, datetime.now(UTC))
    resp.participants = await participants_count(db, survey.id)
    return resp


# --- Списки ------------------------------------------------------------------


@router.get("/learn/surveys", response_model=SurveyListResponse)
async def list_surveys(
    manage: bool = Query(default=False),
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> SurveyListResponse:
    role = await resolve_content_role(db, principal)
    profile = await get_profile(db, principal)
    profile_id = profile.id if profile else None

    if manage and lifecycle.can(role, "publisher"):
        stmt = select(Survey)
    elif manage and role == "author":
        stmt = select(Survey).where(
            (Survey.created_by == principal.employee_id)
            | (
                (Survey.status == "published")
                & visible_filter(Survey, profile_id or UUID(int=0))
            )
        )
    else:
        stmt = select(Survey).where(
            Survey.status == "published",
            visible_filter(Survey, profile_id or UUID(int=0)),
        )
    surveys = list(
        (await db.execute(stmt.order_by(Survey.created_at.desc()))).scalars().all()
    )

    participated: set[UUID] = set()
    if profile_id and surveys:
        participated = {
            r[0]
            for r in await db.execute(
                select(SurveyParticipation.survey_id).where(
                    SurveyParticipation.survey_id.in_([s.id for s in surveys]),
                    SurveyParticipation.profile_id == profile_id,
                )
            )
        }
    items = [
        await _to_response(
            db,
            s,
            profile_id=profile_id,
            with_questions=False,
            participated=s.id in participated,
        )
        for s in surveys
    ]
    return SurveyListResponse(items=items, content_role=role)


@router.get("/learn/surveys/{survey_id}", response_model=SurveyResponse)
async def get_survey(
    survey_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> SurveyResponse:
    role = await resolve_content_role(db, principal)
    survey = await _get_survey_or_404(db, survey_id)
    profile = await get_profile(db, principal)
    profile_id = profile.id if profile else None
    manager = lifecycle.can(role, "publisher") or (
        role == "author" and survey.created_by == principal.employee_id
    )
    if not manager and (
        survey.status != "published" or not await _survey_visible_to(db, survey, profile_id)
    ):
        raise HTTPException(status_code=404, detail="Опрос не найден")
    return await _to_response(db, survey, profile_id=profile_id)


# --- CRUD --------------------------------------------------------------------


@router.post("/learn/surveys", response_model=SurveyResponse, status_code=201)
async def create_survey(
    body: SurveyCreate,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> SurveyResponse:
    await require_content_role(db, principal, "author")
    survey = Survey(
        tenant_id=principal.tenant_id,
        title=body.title,
        description=body.description,
        kind=body.kind,
        is_anonymous=body.is_anonymous,
        opens_at=body.opens_at,
        closes_at=body.closes_at,
        owner_id=principal.employee_id,
        created_by=principal.employee_id,
    )
    db.add(survey)
    await db.flush()
    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor_id=principal.employee_id,
        action="create",
        object_type=_OBJECT_TYPE,
        object_id=survey.id,
        object_label=survey.title,
    )
    await db.commit()
    await db.refresh(survey)
    return await _to_response(db, survey, profile_id=None)


@router.patch("/learn/surveys/{survey_id}", response_model=SurveyResponse)
async def update_survey(
    survey_id: UUID,
    body: SurveyUpdate,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> SurveyResponse:
    role = await require_content_role(db, principal, "author")
    survey = await _get_survey_or_404(db, survey_id)
    _require_manage(survey, principal, role)
    fields = body.model_dump(exclude_unset=True)
    # Анонимность замораживается при публикации (ТЗ/ревью).
    if (
        "is_anonymous" in fields
        and survey.published_at is not None
        and fields["is_anonymous"] != survey.is_anonymous
    ):
        raise HTTPException(
            status_code=422, detail="Анонимность нельзя менять после публикации"
        )
    for name, value in fields.items():
        setattr(survey, name, value)
    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor_id=principal.employee_id,
        action="update",
        object_type=_OBJECT_TYPE,
        object_id=survey.id,
        object_label=survey.title,
    )
    await db.commit()
    await db.refresh(survey)
    return await _to_response(db, survey, profile_id=None)


@router.put("/learn/surveys/{survey_id}/questions", response_model=SurveyResponse)
async def replace_questions(
    survey_id: UUID,
    body: QuestionsReplace,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> SurveyResponse:
    role = await require_content_role(db, principal, "author")
    survey = await _get_survey_or_404(db, survey_id)
    _require_manage(survey, principal, role)
    if survey.published_at is not None:
        raise HTTPException(
            status_code=422,
            detail="Вопросы опубликованного опроса менять нельзя — ответы станут несопоставимы",
        )
    await db.execute(delete(SurveyQuestion).where(SurveyQuestion.survey_id == survey_id))
    for i, q in enumerate(body.questions):
        db.add(
            SurveyQuestion(
                tenant_id=principal.tenant_id,
                survey_id=survey_id,
                qtype=q.qtype,
                prompt=q.prompt.strip(),
                options=q.options,
                required=q.required,
                position=i,
            )
        )
    await db.commit()
    await db.refresh(survey)
    return await _to_response(db, survey, profile_id=None)


@router.delete("/learn/surveys/{survey_id}", status_code=204)
async def delete_survey(
    survey_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> None:
    role = await require_content_role(db, principal, "author")
    survey = await _get_survey_or_404(db, survey_id)
    _require_manage(survey, principal, role)
    if survey.published_at is not None:
        raise HTTPException(status_code=409, detail="Опрос публиковался — используйте архив")
    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor_id=principal.employee_id,
        action="delete",
        object_type=_OBJECT_TYPE,
        object_id=survey.id,
        object_label=survey.title,
    )
    await db.delete(survey)
    await db.commit()


@router.post("/learn/surveys/{survey_id}/status", response_model=SurveyResponse)
async def change_survey_status(
    survey_id: UUID,
    body: dict,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> SurveyResponse:
    new_status = body.get("status")
    if new_status not in ("draft", "review", "published", "archived"):
        raise HTTPException(status_code=422, detail="Некорректный статус")
    role = await require_content_role(db, principal, "author")
    survey = await _get_survey_or_404(db, survey_id)
    _require_manage(survey, principal, role)
    if new_status == "published" and not await _questions(db, survey_id):
        raise HTTPException(status_code=422, detail="Добавьте хотя бы один вопрос")

    # Предупреждение анонимности на маленькую аудиторию — считаем ДО перехода.
    was_published = survey.status == "published"
    lifecycle.transition(
        db,
        survey,
        new_status,
        actor_id=principal.employee_id,
        role=role,
        tenant_id=principal.tenant_id,
        object_type=_OBJECT_TYPE,
        object_label=survey.title,
    )

    if survey.status == "published" and not was_published:
        if survey.audience_id is None:
            rows = await db.execute(
                select(EmployeeProfile.id).where(EmployeeProfile.status == "active")
            )
        else:
            rows = await db.execute(
                select(AudienceMember.profile_id).where(
                    AudienceMember.audience_id == survey.audience_id
                )
            )
        profile_ids = [r[0] for r in rows]
        recipients = await _employee_ids(db, profile_ids)
        await notify_many(
            db,
            tenant_id=survey.tenant_id,
            employee_ids=list(recipients.values()),
            kind="survey.assigned",
            title=survey.title,
            body="Пройдите опрос — это займёт пару минут.",
            url=f"/learn/surveys?s={survey.id}",
            payload={"survey_id": str(survey.id)},
        )
    await db.commit()
    await db.refresh(survey)
    return await _to_response(db, survey, profile_id=None)


@router.put("/learn/surveys/{survey_id}/audience", response_model=SurveyResponse)
async def set_survey_audience(
    survey_id: UUID,
    body: AudienceBody,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> SurveyResponse:
    await require_content_role(db, principal, "publisher")
    survey = await _get_survey_or_404(db, survey_id)
    try:
        audience_id, _diff = await set_object_audience(
            db,
            tenant_id=principal.tenant_id,
            current_audience_id=survey.audience_id,
            is_all=body.is_all,
            rules=_rule_specs(body),
            object_hint=f"{_OBJECT_TYPE}:{survey.id}",
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    survey.audience_id = audience_id
    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor_id=principal.employee_id,
        action="access_change",
        object_type=_OBJECT_TYPE,
        object_id=survey.id,
        object_label=survey.title,
    )
    await db.commit()
    await db.refresh(survey)
    return await _to_response(db, survey, profile_id=None)


# --- Прохождение -------------------------------------------------------------


def _validate_answer(q: SurveyQuestion, value: dict) -> None:
    if q.qtype == "single":
        opt = value.get("option")
        n = len((q.options or {}).get("options", []))
        if not isinstance(opt, int) or not 0 <= opt < n:
            raise HTTPException(status_code=422, detail=f"«{q.prompt[:40]}»: выберите вариант")
    elif q.qtype == "multi":
        opts = value.get("options")
        n = len((q.options or {}).get("options", []))
        if (
            not isinstance(opts, list)
            or not opts
            or not all(isinstance(o, int) and 0 <= o < n for o in opts)
            or len(set(opts)) != len(opts)
        ):
            raise HTTPException(status_code=422, detail=f"«{q.prompt[:40]}»: выберите варианты")
    elif q.qtype == "open":
        txt = value.get("text")
        if not isinstance(txt, str) or not txt.strip() or len(txt) > 4000:
            raise HTTPException(status_code=422, detail=f"«{q.prompt[:40]}»: введите ответ")
    elif q.qtype in ("scale", "enps"):
        val = value.get("value")
        lo, hi = (0, 10) if q.qtype == "enps" else (
            (q.options or {}).get("min", 1),
            (q.options or {}).get("max", 5),
        )
        if not isinstance(val, int) or not lo <= val <= hi:
            raise HTTPException(status_code=422, detail=f"«{q.prompt[:40]}»: оценка {lo}–{hi}")


@router.post("/learn/surveys/{survey_id}/submit", response_model=SurveyResponse)
async def submit_survey(
    survey_id: UUID,
    body: SubmitBody,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> SurveyResponse:
    await enforce_rate_limit(
        bucket="survey:submit",
        employee_id=str(principal.employee_id),
        limit=30,
        window_sec=60,
    )
    survey = await _get_survey_or_404(db, survey_id)
    profile = await get_profile(db, principal)
    if profile is None or not await _survey_visible_to(db, survey, profile.id):
        raise HTTPException(status_code=404, detail="Опрос не найден")
    if not _is_open_now(survey, datetime.now(UTC)):
        raise HTTPException(status_code=422, detail="Опрос закрыт")

    questions = {q.id: q for q in await _questions(db, survey_id)}
    answers_by_q = {a.question_id: a.value for a in body.answers}
    unknown = set(answers_by_q) - set(questions)
    if unknown:
        raise HTTPException(status_code=422, detail="Ответ на несуществующий вопрос")
    for q in questions.values():
        if q.id in answers_by_q:
            _validate_answer(q, answers_by_q[q.id])
        elif q.required:
            raise HTTPException(
                status_code=422, detail=f"«{q.prompt[:40]}» — обязательный вопрос"
            )

    # Повторное прохождение — ON CONFLICT ловит и гонку двойного сабмита.
    result = await db.execute(
        pg_insert(SurveyParticipation)
        .values(survey_id=survey_id, profile_id=profile.id, tenant_id=survey.tenant_id)
        .on_conflict_do_nothing(index_elements=["survey_id", "profile_id"])
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=409, detail="Вы уже проходили этот опрос")

    # Рейтинг (Ф3b): факт участия — «первое действие», ответы не трогаем.
    await award(
        db,
        tenant_id=survey.tenant_id,
        profile_id=profile.id,
        event_type="survey.completed",
        object_type="survey",
        object_id=survey.id,
    )

    answer_set = SurveyAnswerSet(
        tenant_id=survey.tenant_id,
        survey_id=survey_id,
        profile_id=None if survey.is_anonymous else profile.id,
        position_id=profile.position_id,
        store_id=profile.store_id,
        franchisee_id=profile.franchisee_id,
        department_id=profile.department_id,
        org_role=profile.org_role,
    )
    db.add(answer_set)
    await db.flush()
    for question_id, value in answers_by_q.items():
        db.add(
            SurveyAnswer(
                tenant_id=survey.tenant_id,
                answer_set_id=answer_set.id,
                question_id=question_id,
                value=value,
            )
        )
    await db.commit()
    await db.refresh(survey)
    return await _to_response(db, survey, profile_id=profile.id, participated=True)


# --- Результаты --------------------------------------------------------------


@router.get("/learn/surveys/{survey_id}/results", response_model=SurveyResultsResponse)
async def survey_results(
    survey_id: UUID,
    dimension: str | None = Query(default=None),
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> SurveyResultsResponse:
    await require_content_role(db, principal, "publisher")
    survey = await _get_survey_or_404(db, survey_id)
    settings = await get_settings_dict(db, principal.tenant_id)
    k = int(settings.get("survey_k_anonymity", 5))

    if survey.audience_id is None:
        audience_size = (
            await db.execute(
                select(func.count()).select_from(EmployeeProfile).where(
                    EmployeeProfile.status == "active"
                )
            )
        ).scalar_one()
    else:
        audience_size = (
            await db.execute(
                select(func.count()).select_from(AudienceMember).where(
                    AudienceMember.audience_id == survey.audience_id
                )
            )
        ).scalar_one()

    stats = []
    try:
        for q in await _questions(db, survey_id):
            s = await question_stats(db, survey, q, dimension=dimension, k_anonymity=k)
            stats.append(
                QuestionStatsResponse(
                    question_id=s.question_id,
                    qtype=s.qtype,
                    prompt=s.prompt,
                    total_answers=s.total_answers,
                    distribution=s.distribution,
                    texts=s.texts,
                    enps_score=s.enps_score,
                    groups=s.groups,
                )
            )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None

    return SurveyResultsResponse(
        survey_id=survey_id,
        participants=await participants_count(db, survey_id),
        audience_size=audience_size,
        dimension=dimension,
        questions=stats,
    )

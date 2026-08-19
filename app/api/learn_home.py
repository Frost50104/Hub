"""Витрина «Обучение» + learn-профиль (Ф4, ТЗ §3/§16).

Витрина собирает персональную сводку: незавершённое обучение → обязательные
ознакомления → новинки → активные опросы → рейтинг-виджет. Каждый блок
переиспользует готовую доменную логику (list_courses, _not_acked, rating).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends
from signaris_auth import Principal
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.courses import list_courses
from app.api.library import _effective_ack_version, _not_acked, ack_deadline_for
from app.api.products import _photo_urls
from app.api.quizzes import rating as rating_endpoint
from app.deps import get_db, require_auth
from app.models.activity import ActivityEvent
from app.models.audience import AudienceMember
from app.models.library import LibraryMaterial
from app.models.org import Department, Position, Store
from app.models.product import ProductCard
from app.models.quiz import QuizQuestion
from app.models.search_document import SearchDocument
from app.models.survey import Survey, SurveyParticipation, SurveyQuestion
from app.schemas.product import (
    HomeAck,
    HomeAssessment,
    HomeCourse,
    HomeNovelty,
    HomeRating,
    HomeResponse,
    HomeSurvey,
    LearnProfileResponse,
)
from app.services.audience_resolver import visible_filter
from app.services.content_access import resolve_content_role
from app.services.org_scope import get_profile

router = APIRouter(tags=["learn-home"])

AUTH_AVATAR_BASE = "https://auth.signaris.ru/api/avatars"


@router.get("/learn/home", response_model=HomeResponse)
async def learn_home(
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> HomeResponse:
    profile = await get_profile(db, principal)
    profile_id = profile.id if profile else None

    # 1) Обучение в работе: видимые курсы, назначенные/обязательные, не пройденные.
    course_list = await list_courses(False, principal, db)
    courses = [
        HomeCourse(
            id=c.id,
            title=c.title,
            course_type=c.course_type,
            lessons_total=c.lessons_total,
            lessons_completed=c.lessons_completed,
            due_at=c.due_at,
        )
        for c in course_list.items
        if c.enrolled and not c.completed
    ][:5]

    # 2) Обязательные ознакомления без подписи.
    pending_acks: list[HomeAck] = []
    if profile_id:
        materials = (
            (
                await db.execute(
                    select(LibraryMaterial).where(
                        LibraryMaterial.status == "published",
                        LibraryMaterial.requires_acknowledgement.is_(True),
                        visible_filter(LibraryMaterial, profile_id),
                    )
                )
            )
            .scalars()
            .all()
        )
        granted_at_by_audience: dict[UUID, datetime] = {
            r[0]: r[1]
            for r in await db.execute(
                select(AudienceMember.audience_id, AudienceMember.granted_at).where(
                    AudienceMember.profile_id == profile_id
                )
            )
        }
        for material in materials:
            if await _not_acked(db, material, [profile_id]):
                # Та же формула, что в библиотеке: попавший в аудиторию позже
                # публикации получает свои дни целиком.
                deadline = ack_deadline_for(
                    material,
                    granted_at_by_audience.get(material.audience_id)
                    if material.audience_id
                    else None,
                )
                pending_acks.append(
                    HomeAck(
                        id=material.id,
                        title=material.title,
                        deadline_at=deadline,
                    )
                )
        pending_acks = pending_acks[:5]
        _ = _effective_ack_version  # версия проверяется на странице материала

    # 3) Новинки — свежее из поискового индекса (только published-контент).
    novelty_rows = (
        (
            await db.execute(
                select(SearchDocument)
                .where(
                    visible_filter(SearchDocument, profile_id or UUID(int=0)),
                    SearchDocument.published_at.is_not(None),
                )
                .order_by(SearchDocument.published_at.desc())
                .limit(5)
            )
        )
        .scalars()
        .all()
    )
    product_photos: dict[UUID, str] = {}
    product_ids = [d.object_id for d in novelty_rows if d.object_type == "product"]
    if product_ids:
        for card in (
            (
                await db.execute(
                    select(ProductCard).where(ProductCard.id.in_(product_ids))
                )
            )
            .scalars()
            .all()
        ):
            urls = _photo_urls(card)
            if urls:
                product_photos[card.id] = urls[0]
    novelties = [
        HomeNovelty(
            object_type=d.object_type,
            object_id=d.object_id,
            title=d.title,
            url_path=d.url_path,
            published_at=d.published_at,
            image_url=product_photos.get(d.object_id),
        )
        for d in novelty_rows
    ]

    # 4) Активные опросы, которые ещё не проходил.
    surveys: list[HomeSurvey] = []
    if profile_id:
        now = datetime.now(UTC)
        survey_rows = (
            (
                await db.execute(
                    select(Survey).where(
                        Survey.status == "published",
                        visible_filter(Survey, profile_id),
                        ~select(SurveyParticipation.profile_id)
                        .where(
                            SurveyParticipation.survey_id == Survey.id,
                            SurveyParticipation.profile_id == profile_id,
                        )
                        .exists(),
                    )
                )
            )
            .scalars()
            .all()
        )
        open_surveys = [
            s
            for s in survey_rows
            if (s.opens_at is None or s.opens_at <= now)
            and (s.closes_at is None or s.closes_at > now)
        ][:5]
        question_counts: dict[UUID, int] = {}
        if open_surveys:
            question_counts = {
                r[0]: r[1]
                for r in await db.execute(
                    select(SurveyQuestion.survey_id, func.count())
                    .where(SurveyQuestion.survey_id.in_([s.id for s in open_surveys]))
                    .group_by(SurveyQuestion.survey_id)
                )
            }
        surveys = [
            HomeSurvey(
                id=s.id,
                title=s.title,
                kind=s.kind,
                closes_at=s.closes_at,
                question_count=question_counts.get(s.id, 0),
                is_anonymous=s.is_anonymous,
            )
            for s in open_surveys
        ]

    # 5) Активные аттестации, которые ещё не сданы (QA-находка: сотрудник
    # узнавал об аттестации только из уведомления или нав-пункта).
    assessments: list[HomeAssessment] = []
    if profile_id:
        from app.api.assessments import _campaign_quiz, _in_window
        from app.models.assessment import AssessmentCampaign
        from app.models.quiz import QuizAttempt

        now = datetime.now(UTC)
        member_of = select(AudienceMember.audience_id).where(
            AudienceMember.profile_id == profile_id
        )
        campaign_rows = (
            (
                await db.execute(
                    select(AssessmentCampaign)
                    .where(
                        AssessmentCampaign.status == "active",
                        (AssessmentCampaign.audience_id.is_(None))
                        | AssessmentCampaign.audience_id.in_(member_of),
                    )
                    .order_by(AssessmentCampaign.ends_at.asc().nulls_last())
                )
            )
            .scalars()
            .all()
        )
        for campaign in campaign_rows:
            if not _in_window(campaign, now):
                continue
            quiz = await _campaign_quiz(db, campaign.id)
            if quiz is None:
                continue
            passed = (
                await db.execute(
                    select(QuizAttempt.id).where(
                        QuizAttempt.quiz_id == quiz.id,
                        QuizAttempt.profile_id == profile_id,
                        QuizAttempt.passed.is_(True),
                    )
                )
            ).first()
            if passed is None:
                question_count = (
                    await db.execute(
                        select(func.count())
                        .select_from(QuizQuestion)
                        .where(QuizQuestion.quiz_id == quiz.id)
                    )
                ).scalar_one()
                assessments.append(
                    HomeAssessment(
                        id=campaign.id,
                        title=campaign.title,
                        ends_at=campaign.ends_at,
                        question_count=int(question_count),
                    )
                )
            if len(assessments) >= 5:
                break

    # 6) Рейтинг-виджет: моё место за месяц по всей сети.
    home_rating = None
    if profile_id:
        rating_data = await rating_endpoint("month", "all", principal, db)
        me = rating_data.me
        # Дельта за 7 дней — по тем же activity_events, что и сам рейтинг.
        week_points = (
            await db.execute(
                select(func.coalesce(func.sum(ActivityEvent.points), 0)).where(
                    ActivityEvent.profile_id == profile_id,
                    ActivityEvent.occurred_at >= datetime.now(UTC) - timedelta(days=7),
                )
            )
        ).scalar_one()
        home_rating = HomeRating(
            points=me.points if me else 0.0,
            rank=me.rank if me else None,
            total_participants=rating_data.total_participants,
            delta_week=float(week_points or 0),
        )

    return HomeResponse(
        courses=courses,
        pending_acks=pending_acks,
        novelties=novelties,
        surveys=surveys,
        rating=home_rating,
        assessments=assessments,
    )


@router.get("/learn/profile", response_model=LearnProfileResponse)
async def learn_profile(
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> LearnProfileResponse:
    profile = await get_profile(db, principal)
    role = await resolve_content_role(db, principal)
    if profile is None:
        return LearnProfileResponse(
            profile_id=None,
            full_name=principal.full_name or principal.email,
            email=principal.email,
            avatar_url=f"{AUTH_AVATAR_BASE}/{principal.employee_id}",
            position_name=None,
            store_name=None,
            department_name=None,
            org_role=None,
            content_role=role,
            status_text=None,
            hired_at=None,
            tenure_days=None,
        )

    position_name = store_name = department_name = None
    if profile.position_id:
        position_name = (
            await db.execute(select(Position.name).where(Position.id == profile.position_id))
        ).scalar_one_or_none()
    if profile.store_id:
        store_name = (
            await db.execute(select(Store.name).where(Store.id == profile.store_id))
        ).scalar_one_or_none()
    if profile.department_id:
        department_name = (
            await db.execute(
                select(Department.name).where(Department.id == profile.department_id)
            )
        ).scalar_one_or_none()

    tenure_days = None
    if profile.hired_at:
        tenure_days = (datetime.now(UTC).date() - profile.hired_at).days

    return LearnProfileResponse(
        profile_id=profile.id,
        full_name=profile.full_name,
        email=profile.email,
        avatar_url=f"{AUTH_AVATAR_BASE}/{principal.employee_id}",
        position_name=position_name,
        store_name=store_name,
        department_name=department_name,
        org_role=profile.org_role,
        content_role=role,
        status_text=profile.status_text,
        hired_at=profile.hired_at,
        tenure_days=tenure_days,
    )

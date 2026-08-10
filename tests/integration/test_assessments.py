"""Integration-тесты Ф8: кампании, доступ по аудитории/окну/статусу,
импорт вопросов, прохождение через квиз-движок, отчёт."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.assessments import (
    CampaignUpsert,
    ImportBody,
    activate_campaign,
    campaign_report,
    create_campaign,
    import_questions,
    list_campaigns,
    update_campaign,
    upsert_campaign_quiz,
)
from app.api.quizzes import (
    review_attempt,
    save_answer,
    start_or_resume_attempt,
    submit_attempt,
)
from app.models.audience import Audience, AudienceMember
from app.models.notification import Notification
from app.schemas.quiz import AnswerBody, QuizUpsert, ReviewBody
from tests.integration.test_courses import _mk_course, _mk_member
from tests.integration.test_quizzes import (
    _mk_publisher,
    _open_draft,
    _publish_quiz,
    _single_draft,
)

pytestmark = pytest.mark.integration


async def _mk_admin(db, tenant_id, email="admin@t.ru"):
    """hub-admin: управление кампаниями — только эта роль (ОС 2026-08-10).
    Роль живёт в JWT (product_roles), профиль не обязателен."""
    principal, profile = await _mk_member(db, tenant_id, email=email)
    principal.product_roles["hub"] = "admin"
    return principal, profile


@pytest.fixture(autouse=True)
def _no_push(monkeypatch):
    from app.api import quizzes as quizzes_api
    from app.services import notify_batch

    async def _noop_rate_limit(**kw) -> None:
        return None

    monkeypatch.setattr(quizzes_api, "enforce_rate_limit", _noop_rate_limit)
    monkeypatch.setattr(notify_batch, "_schedule_push_batch", lambda **kw: None)


async def _mk_campaign(db, hr, *, title="Аттестация бариста", **kw):
    campaign = await create_campaign(CampaignUpsert(title=title, **kw), hr, db)
    await upsert_campaign_quiz(
        campaign.id,
        QuizUpsert(
            title=title,
            status="draft",
            pass_score_pct=80,
            attempts_limit=1,
            shuffle_questions=False,
            shuffle_options=False,
            questions=[_single_draft(correct=1)],
        ),
        hr,
        db,
    )
    return campaign


async def test_access_by_audience_window_and_status(
    db: AsyncSession, tenant_id: uuid.UUID
):
    hr, _ = await _mk_admin(db, tenant_id)
    member, profile = await _mk_member(db, tenant_id, email="a1@t.ru")

    audience = Audience(tenant_id=tenant_id)
    db.add(audience)
    await db.flush()

    campaign = await _mk_campaign(db, hr)
    from app.models.assessment import AssessmentCampaign

    row = await db.get(AssessmentCampaign, campaign.id)
    row.audience_id = audience.id
    await db.flush()

    # Draft: сотрудник не видит, попытка недоступна.
    listing = await list_campaigns(member, db)
    assert all(c.id != campaign.id for c in listing)

    await activate_campaign(campaign.id, hr, db)

    # Активна, но профиль не в аудитории → не видит, попытка 404.
    listing = await list_campaigns(member, db)
    assert all(c.id != campaign.id for c in listing)
    with pytest.raises(HTTPException) as exc:
        await start_or_resume_attempt(campaign.quiz_id, member, db)
    assert exc.value.status_code == 404

    # Включили в аудиторию → видит и может проходить.
    db.add(AudienceMember(tenant_id=tenant_id, audience_id=audience.id, profile_id=profile.id))
    await db.flush()
    listing = await list_campaigns(member, db)
    mine = next(c for c in listing if c.id == campaign.id)
    assert mine.my_state is not None and mine.my_state.can_start

    # Окно в прошлом → доступ закрыт.
    row.ends_at = datetime.now(UTC) - timedelta(hours=1)
    await db.flush()
    with pytest.raises(HTTPException) as exc:
        await start_or_resume_attempt(campaign.quiz_id, member, db)
    assert exc.value.status_code == 404


async def test_pass_flow_and_report(db: AsyncSession, tenant_id: uuid.UUID):
    hr, _ = await _mk_admin(db, tenant_id)
    member, profile = await _mk_member(db, tenant_id, email="a2@t.ru")

    campaign = await _mk_campaign(db, hr, title="Годовая аттестация")
    await activate_campaign(campaign.id, hr, db)

    # Уведомление аудитории (всем активным — audience NULL).
    notif = (
        await db.execute(
            select(Notification).where(
                Notification.kind == "assessment.assigned",
                Notification.payload["campaign_id"].astext == str(campaign.id),
                Notification.employee_id == member.employee_id,
            )
        )
    ).scalars().all()
    assert len(notif) == 1

    attempt = await start_or_resume_attempt(campaign.quiz_id, member, db)
    qid = attempt.questions[0].id
    await save_answer(attempt.id, AnswerBody(question_id=qid, value=1), member, db)
    submitted = await submit_attempt(attempt.id, member, db)
    assert submitted.passed is True

    report = await campaign_report(campaign.id, hr, db)
    my_row = next(r for r in report.rows if r.profile_id == profile.id)
    assert my_row.status == "passed" and my_row.score_pct == 100

    # Лимит попыток 1 — вторая попытка недоступна.
    with pytest.raises(HTTPException) as exc:
        await start_or_resume_attempt(campaign.quiz_id, member, db)
    assert exc.value.status_code == 409


async def test_import_questions_from_lesson_quiz(
    db: AsyncSession, tenant_id: uuid.UUID
):
    hr, _ = await _mk_admin(db, tenant_id)
    _course, lessons = await _mk_course(db, tenant_id, lesson_count=1)
    lesson_quiz = await _publish_quiz(
        db, hr, lessons[0].id, [_single_draft(correct=0), _single_draft(correct=1)]
    )

    campaign = await _mk_campaign(db, hr, title="Импорт-тест")
    result = await import_questions(
        campaign.id, ImportBody(quiz_id=lesson_quiz.id), hr, db
    )
    # 1 собственный + 2 импортированных, порядок сохранён.
    assert len(result.questions) == 3
    assert [q.position for q in result.questions] == [0, 1, 2]


async def test_publisher_cannot_manage_campaigns(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """ОС 2026-08-10: управление кампаниями — только hub-admin. Publisher
    получает 403 на create/patch/activate и участвует на общих основаниях."""
    admin, _ = await _mk_admin(db, tenant_id)
    publisher, _ = await _mk_publisher(db, tenant_id)

    with pytest.raises(HTTPException) as exc:
        await create_campaign(CampaignUpsert(title="Чужая"), publisher, db)
    assert exc.value.status_code == 403

    campaign = await _mk_campaign(db, admin, title="Админская")
    with pytest.raises(HTTPException) as exc:
        await update_campaign(campaign.id, CampaignUpsert(title="Взлом"), publisher, db)
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException) as exc:
        await activate_campaign(campaign.id, publisher, db)
    assert exc.value.status_code == 403

    # Активная кампания без аудитории: publisher — обычный участник
    # (my_state заполнен), а не менеджер, и БЕЗ обхода audience-гейта.
    await activate_campaign(campaign.id, admin, db)
    listing = await list_campaigns(publisher, db)
    mine = next(c for c in listing if c.id == campaign.id)
    assert mine.my_state is not None and mine.my_state.can_start


async def test_publisher_still_reviews_campaign_attempts(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Решение ОС: review открытых ответов остаётся HR (publisher), хотя
    управление кампаниями закрыто на админов."""
    admin, _ = await _mk_admin(db, tenant_id)
    publisher, _ = await _mk_publisher(db, tenant_id)
    member, _profile = await _mk_member(db, tenant_id, email="a3@t.ru")

    campaign = await create_campaign(CampaignUpsert(title="С открытым"), admin, db)
    await upsert_campaign_quiz(
        campaign.id,
        QuizUpsert(
            title="С открытым",
            status="draft",
            pass_score_pct=60,
            attempts_limit=1,
            shuffle_questions=False,
            shuffle_options=False,
            questions=[_single_draft(correct=1), _open_draft()],
        ),
        admin,
        db,
    )
    await activate_campaign(campaign.id, admin, db)

    attempt = await start_or_resume_attempt(campaign.quiz_id, member, db)
    single_id = next(q.id for q in attempt.questions if q.qtype == "single")
    open_id = next(q.id for q in attempt.questions if q.qtype == "open")
    await save_answer(attempt.id, AnswerBody(question_id=single_id, value=1), member, db)
    await save_answer(
        attempt.id,
        AnswerBody(question_id=open_id, value="Развёрнутый ответ"),
        member,
        db,
    )
    submitted = await submit_attempt(attempt.id, member, db)
    assert submitted.needs_review is True

    reviewed = await review_attempt(
        attempt.id, ReviewBody(scores={open_id: 2}), publisher, db
    )
    assert reviewed.needs_review is False and reviewed.passed is True

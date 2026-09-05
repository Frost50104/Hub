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
    close_campaign,
    create_campaign,
    delete_campaign,
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
from app.schemas.quiz import AnswerBody, QuestionDraft, QuizUpsert, ReviewBody
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


async def test_saving_the_imported_set_keeps_everything(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """ОС 26.08: «вопросы импортируются, но не появляются».

    Ручка кампании — REPLACE: она сносит все вопросы квиза и вставляет то, что
    прислал клиент. Значит редактор ОБЯЗАН пересеять локальный набор ответом
    импорта: сохранение старым набором физически удаляет импортированное.
    Тест фиксирует обе стороны — и то, что ответ импорта самодостаточен, и то,
    чем оборачивается сохранение мимо него.
    """
    hr, _ = await _mk_admin(db, tenant_id)
    _course, lessons = await _mk_course(db, tenant_id, lesson_count=1)
    lesson_quiz = await _publish_quiz(
        db, hr, lessons[0].id, [_single_draft(correct=0), _single_draft(correct=1)]
    )
    campaign = await _mk_campaign(db, hr, title="Сохранение после импорта")

    imported = await import_questions(
        campaign.id, ImportBody(quiz_id=lesson_quiz.id), hr, db
    )
    assert len(imported.questions) == 3

    def _upsert(questions):
        return QuizUpsert(
            title="Сохранение после импорта",
            status="draft",
            pass_score_pct=80,
            attempts_limit=1,
            shuffle_questions=False,
            shuffle_options=False,
            questions=questions,
        )

    # Так делает исправленный редактор: набор взят из ответа импорта.
    saved = await upsert_campaign_quiz(
        campaign.id,
        _upsert(
            [
                QuestionDraft(
                    qtype=q.qtype,
                    prompt=q.prompt,
                    media_id=q.media_id,
                    options=q.options,
                    answer=q.answer,
                    points=q.points,
                )
                for q in imported.questions
            ]
        ),
        hr,
        db,
    )
    assert len(saved.questions) == 3

    # А так было до правки: локальный набор отстал на импорт — и импорт исчез.
    lost = await upsert_campaign_quiz(
        campaign.id, _upsert([_single_draft(correct=1)]), hr, db
    )
    assert len(lost.questions) == 1


async def test_publisher_cannot_import_questions(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Кнопка импорта спрятана не из вкусовщины: ручка — admin-only.

    Publisher добирался до неё, выбирал урок и получал 403 в конце пути.
    """
    admin, _ = await _mk_admin(db, tenant_id)
    publisher, _ = await _mk_publisher(db, tenant_id)
    _course, lessons = await _mk_course(db, tenant_id, lesson_count=1)
    lesson_quiz = await _publish_quiz(db, admin, lessons[0].id, [_single_draft()])
    campaign = await _mk_campaign(db, admin, title="Импорт publisher")

    with pytest.raises(HTTPException) as exc:
        await import_questions(
            campaign.id, ImportBody(quiz_id=lesson_quiz.id), publisher, db
        )
    assert exc.value.status_code == 403


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


async def test_review_notification_points_at_assessments_not_null_course(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Квиз кампании не принадлежит курсу — ссылка в уведомлении обязана вести
    в аттестации.

    Раньше URL строился как `/learn/courses/{quiz.course_id}`, а у квиза
    кампании course_id = NULL: сотрудник открывал письмо «тест проверен» и
    попадал на «/learn/courses/None».
    """
    admin, _ = await _mk_admin(db, tenant_id, email="admin-url@t.ru")
    publisher, _ = await _mk_publisher(db, tenant_id)
    member, _profile = await _mk_member(db, tenant_id, email="a-url@t.ru")

    campaign = await create_campaign(CampaignUpsert(title="Ссылка"), admin, db)
    await upsert_campaign_quiz(
        campaign.id,
        QuizUpsert(
            title="Ссылка",
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
        attempt.id, AnswerBody(question_id=open_id, value="Ответ"), member, db
    )
    await submit_attempt(attempt.id, member, db)
    await review_attempt(attempt.id, ReviewBody(scores={open_id: 2}), publisher, db)

    rows = (
        await db.execute(
            select(Notification).where(Notification.kind == "quiz.reviewed")
        )
    ).scalars().all()
    assert rows, "уведомление о проверке не создано"
    assert all(n.url == "/learn/assessments" for n in rows), [n.url for n in rows]
    assert all("None" not in (n.url or "") for n in rows)


# ─── Удаление кампании (27.08) ───────────────────────────────────────────────
#
# До этого сервер отдавал 409 всему, кроме черновика. Владелец решил открыть
# удаление ЗАВЕРШЁННЫХ: они копятся в списке, а убрать их было нечем. Цена —
# каскад уносит тест, вопросы и все попытки, то есть саму запись о том, кто
# аттестован. Поэтому ниже проверяются обе границы: что завершённую удалить
# можно, а запущенную по-прежнему нельзя.


async def test_closed_campaign_can_be_deleted_with_its_results(
    db: AsyncSession, tenant_id: uuid.UUID
):
    from app.models.quiz import Quiz, QuizAttempt

    hr, _ = await _mk_admin(db, tenant_id, email=f"hr-{uuid.uuid4().hex[:6]}@t.ru")
    campaign = await _mk_campaign(db, hr, title="Закрытая")
    await activate_campaign(campaign.id, hr, db)
    await close_campaign(campaign.id, hr, db)
    quiz_id = (
        await db.execute(select(Quiz.id).where(Quiz.campaign_id == campaign.id))
    ).scalar_one()

    await delete_campaign(campaign.id, hr, db)

    assert (
        await db.execute(select(Quiz.id).where(Quiz.id == quiz_id))
    ).scalar_one_or_none() is None
    assert (
        await db.execute(select(QuizAttempt.id).where(QuizAttempt.quiz_id == quiz_id))
    ).scalars().all() == []


async def test_active_campaign_still_cannot_be_deleted(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Граница, которая не должна съехать: у людей она сейчас на экране."""
    hr, _ = await _mk_admin(db, tenant_id, email=f"hr-{uuid.uuid4().hex[:6]}@t.ru")
    campaign = await _mk_campaign(db, hr, title="Идёт")
    await activate_campaign(campaign.id, hr, db)

    with pytest.raises(HTTPException) as exc:
        await delete_campaign(campaign.id, hr, db)
    assert exc.value.status_code == 409
    assert "закройте" in exc.value.detail


async def test_draft_campaign_still_deletable(db: AsyncSession, tenant_id: uuid.UUID):
    hr, _ = await _mk_admin(db, tenant_id, email=f"hr-{uuid.uuid4().hex[:6]}@t.ru")
    campaign = await _mk_campaign(db, hr, title="Черновик")

    await delete_campaign(campaign.id, hr, db)

    assert [c for c in await list_campaigns(hr, db) if c.id == campaign.id] == []


async def test_delete_writes_audit_with_lost_attempt_count(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Объекта не станет — масштаб потери обязан остаться в журнале."""
    from app.models.audit import AuditLog

    hr, _ = await _mk_admin(db, tenant_id, email=f"hr-{uuid.uuid4().hex[:6]}@t.ru")
    campaign = await _mk_campaign(db, hr, title="Под удаление")
    await activate_campaign(campaign.id, hr, db)
    await close_campaign(campaign.id, hr, db)

    await delete_campaign(campaign.id, hr, db)

    row = (
        await db.execute(
            select(AuditLog)
            .where(
                AuditLog.object_type == "assessment_campaign",
                AuditLog.object_id == campaign.id,
                AuditLog.action == "delete",
            )
        )
    ).scalar_one()
    assert row.object_label == "Под удаление"
    assert (row.diff or {}).get("status") == "closed"
    assert "attempts" in (row.diff or {})


# ─── Разбор ответов в отчёте (02.09) ─────────────────────────────────────────


async def test_report_attempt_detail_for_admin(db: AsyncSession, tenant_id: uuid.UUID):
    """Admin видит разбор попытки: ответы человека, вердикты и правильные
    варианты — В ОБХОД show_correct_answers (флаг защищает пересдачи от
    сотрудника, а не прячет ответы от того, кто их сам ввёл в редакторе).
    Плюс отчёт несёт attempt_id лучшей попытки и агрегат question_stats."""
    from app.api.assessments import campaign_attempt_detail

    hr, _ = await _mk_admin(db, tenant_id, email=f"hr-{uuid.uuid4().hex[:6]}@t.ru")
    member, profile = await _mk_member(
        db, tenant_id, email=f"m-{uuid.uuid4().hex[:6]}@t.ru"
    )
    campaign = await _mk_campaign(db, hr, title="Разбор ответов")
    await activate_campaign(campaign.id, hr, db)

    attempt = await start_or_resume_attempt(campaign.quiz_id, member, db)
    qid = attempt.questions[0].id
    # Отвечаем НЕВЕРНО (правильный — вариант 1).
    await save_answer(attempt.id, AnswerBody(question_id=qid, value=0), member, db)
    await submit_attempt(attempt.id, member, db)

    report = await campaign_report(campaign.id, hr, db)
    row = next(r for r in report.rows if r.profile_id == profile.id)
    assert row.status == "failed"
    assert row.attempt_id is not None

    detail = await campaign_attempt_detail(campaign.id, row.attempt_id, hr, db)
    assert detail.employee_name == profile.full_name
    assert detail.answers[qid] == 0
    assert detail.results[qid] is False
    assert qid in detail.correct_answers  # правильные ответы доехали

    # Агрегат: одна завершённая попытка, одна ошибка — 100%.
    assert report.question_stats is not None
    stat = next(s for s in report.question_stats if s.wrong >= 1)
    assert stat.attempts >= 1 and stat.fail_rate_pct > 0


async def test_report_attempt_detail_gates(db: AsyncSession, tenant_id: uuid.UUID):
    """Разбор — только hub-admin (решение владельца 02.09): publisher — 403,
    его отчёт — без question_stats; попытка чужой кампании — 404 даже админу."""
    from app.api.assessments import campaign_attempt_detail

    hr, _ = await _mk_admin(db, tenant_id, email=f"hr-{uuid.uuid4().hex[:6]}@t.ru")
    publisher, _ = await _mk_publisher(db, tenant_id)
    member, profile = await _mk_member(
        db, tenant_id, email=f"m-{uuid.uuid4().hex[:6]}@t.ru"
    )
    campaign = await _mk_campaign(db, hr, title="Гейты разбора")
    await activate_campaign(campaign.id, hr, db)
    attempt = await start_or_resume_attempt(campaign.quiz_id, member, db)
    qid = attempt.questions[0].id
    await save_answer(attempt.id, AnswerBody(question_id=qid, value=1), member, db)
    await submit_attempt(attempt.id, member, db)

    report = await campaign_report(campaign.id, hr, db)
    row = next(r for r in report.rows if r.profile_id == profile.id)
    assert row.attempt_id is not None

    with pytest.raises(HTTPException) as exc:
        await campaign_attempt_detail(campaign.id, row.attempt_id, publisher, db)
    assert exc.value.status_code == 403

    pub_report = await campaign_report(campaign.id, publisher, db)
    assert pub_report.question_stats is None

    other = await _mk_campaign(db, hr, title="Чужая кампания")
    with pytest.raises(HTTPException) as exc:
        await campaign_attempt_detail(other.id, row.attempt_id, hr, db)
    assert exc.value.status_code == 404


async def test_list_reports_attempt_count_to_manager(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Число, которое покажут в предупреждении, должно приходить в списке."""
    hr, _ = await _mk_admin(db, tenant_id, email=f"hr-{uuid.uuid4().hex[:6]}@t.ru")
    campaign = await _mk_campaign(db, hr, title="Со счётчиком")

    view = next(c for c in await list_campaigns(hr, db) if c.id == campaign.id)
    assert view.attempt_count == 0

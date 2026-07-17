"""Integration-тесты опросов (Ф2): анти-деанон инварианты + k-anonymity."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employee_profile import EmployeeProfile
from app.models.org import Store
from app.models.survey import (
    Survey,
    SurveyAnswer,
    SurveyAnswerSet,
    SurveyParticipation,
    SurveyQuestion,
)
from app.services.survey_stats import SUPPRESSED, enps_from_distribution, question_stats

pytestmark = pytest.mark.integration


async def _mk_survey(db: AsyncSession, tenant_id: uuid.UUID, **kw) -> Survey:
    survey = Survey(tenant_id=tenant_id, title=kw.pop("title", "Пульс"), **kw)
    db.add(survey)
    await db.flush()
    return survey


async def _submit(
    db: AsyncSession,
    survey: Survey,
    question: SurveyQuestion,
    profile: EmployeeProfile,
    value: dict,
) -> None:
    """Мини-копия транзакции submit из API."""
    db.add(
        SurveyParticipation(
            survey_id=survey.id, profile_id=profile.id, tenant_id=survey.tenant_id
        )
    )
    answer_set = SurveyAnswerSet(
        tenant_id=survey.tenant_id,
        survey_id=survey.id,
        profile_id=None if survey.is_anonymous else profile.id,
        position_id=profile.position_id,
        store_id=profile.store_id,
        org_role=profile.org_role,
    )
    db.add(answer_set)
    await db.flush()
    db.add(
        SurveyAnswer(
            tenant_id=survey.tenant_id,
            answer_set_id=answer_set.id,
            question_id=question.id,
            value=value,
        )
    )
    await db.flush()


async def test_anonymous_answer_sets_carry_no_identity(
    db: AsyncSession, tenant_id: uuid.UUID
):
    survey = await _mk_survey(db, tenant_id, is_anonymous=True, status="published")
    q = SurveyQuestion(
        tenant_id=tenant_id, survey_id=survey.id, qtype="scale",
        prompt="Как настроение?", options={"min": 1, "max": 5},
    )
    db.add(q)
    profile = EmployeeProfile(tenant_id=tenant_id, email="a@t.ru", full_name="А")
    db.add(profile)
    await db.flush()

    await _submit(db, survey, q, profile, {"value": 4})

    answer_set = (
        await db.execute(select(SurveyAnswerSet).where(SurveyAnswerSet.survey_id == survey.id))
    ).scalar_one()
    # Ни identity, ни timestamp — только демографический снапшот.
    assert answer_set.profile_id is None
    assert not hasattr(answer_set, "created_at")
    # Факт участия при этом зафиксирован (повторно не пройти).
    participation = (
        await db.execute(
            select(SurveyParticipation).where(SurveyParticipation.survey_id == survey.id)
        )
    ).scalar_one()
    assert participation.profile_id == profile.id


async def test_double_submit_conflict(db: AsyncSession, tenant_id: uuid.UUID):
    survey = await _mk_survey(db, tenant_id, status="published")
    profile = EmployeeProfile(tenant_id=tenant_id, email="b@t.ru", full_name="Б")
    db.add(profile)
    await db.flush()
    db.add(
        SurveyParticipation(
            survey_id=survey.id, profile_id=profile.id, tenant_id=tenant_id
        )
    )
    await db.flush()

    # Повторный сабмит: ON CONFLICT DO NOTHING → rowcount 0 (API вернёт 409).
    result = await db.execute(
        pg_insert(SurveyParticipation)
        .values(survey_id=survey.id, profile_id=profile.id, tenant_id=tenant_id)
        .on_conflict_do_nothing(index_elements=["survey_id", "profile_id"])
    )
    assert result.rowcount == 0


async def test_k_anonymity_suppresses_small_groups(db: AsyncSession, tenant_id: uuid.UUID):
    survey = await _mk_survey(db, tenant_id, is_anonymous=True, status="published")
    q = SurveyQuestion(
        tenant_id=tenant_id, survey_id=survey.id, qtype="enps",
        prompt="Порекомендуете UPPETIT?",
    )
    db.add(q)
    await db.flush()

    big = Store(tenant_id=tenant_id, name="Большой")
    small = Store(tenant_id=tenant_id, name="Маленький")
    db.add_all([big, small])
    await db.flush()
    big_store, small_store = big.id, small.id
    # 6 ответов из большого магазина (промоутеры), 3 — из маленького (критики).
    for i in range(6):
        profile = EmployeeProfile(
            tenant_id=tenant_id, email=f"big{i}@t.ru", full_name=f"Б{i}", store_id=big_store
        )
        db.add(profile)
        await db.flush()
        await _submit(db, survey, q, profile, {"value": 10})
    for i in range(3):
        profile = EmployeeProfile(
            tenant_id=tenant_id, email=f"small{i}@t.ru", full_name=f"М{i}", store_id=small_store
        )
        db.add(profile)
        await db.flush()
        await _submit(db, survey, q, profile, {"value": 2})

    # Общий агрегат — по всем.
    total = await question_stats(db, survey, q, dimension=None, k_anonymity=5)
    assert total.total_answers == 9
    assert total.enps_score == round(100 * (6 - 3) / 9, 1)

    # Срез по магазину: маленькая группа подавлена, большая видна.
    sliced = await question_stats(db, survey, q, dimension="store_id", k_anonymity=5)
    assert sliced.groups[str(small_store)] == SUPPRESSED
    big = sliced.groups[str(big_store)]
    assert big["total"] == 6 and big["enps_score"] == 100.0

    # Недопустимое измерение → ошибка (комбинированные срезы запрещены).
    with pytest.raises(ValueError, match="измерение"):
        await question_stats(db, survey, q, dimension="store_id,position_id", k_anonymity=5)


def test_enps_formula():
    assert enps_from_distribution({"10": 6, "2": 3}) == round(100 * 3 / 9, 1)
    # 7-8 — нейтралы: 1 промоутер + 1 нейтрал = +50.
    assert enps_from_distribution({"9": 1, "7": 1}) == 50.0
    # Промоутер и критик гасят друг друга.
    assert enps_from_distribution({"9": 1, "5": 1}) == 0.0
    assert enps_from_distribution({}) is None

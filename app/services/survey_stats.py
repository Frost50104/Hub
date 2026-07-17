"""Агрегаты опросов — ЕДИНСТВЕННЫЙ выход данных ответов наружу (Ф2).

Инварианты анти-деанонимизации (adversarial-ревью §18-19, §7 data-линза):
- для АНОНИМНЫХ опросов срез возможен только по ОДНОМУ измерению за раз
  (комбинации → разностная деанонимизация «П14 минус стажёры»);
- k-anonymity: группа среза с < K ответами подавляется («недостаточно
  ответов»), K — learning_settings.survey_k_anonymity (дефолт 5);
- открытые ответы отдаются без демографии, порядок — по random UUID
  answer_set (не по времени);
- API/экспорт/BI обязаны ходить сюда, не в таблицы напрямую.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.survey import Survey, SurveyAnswer, SurveyAnswerSet, SurveyQuestion

DIMENSIONS = ("position_id", "store_id", "franchisee_id", "department_id", "org_role")

SUPPRESSED = "suppressed"


@dataclass
class QuestionStats:
    question_id: UUID
    qtype: str
    prompt: str
    total_answers: int
    # single/multi: {option_index: count}; scale/enps: {value: count}
    distribution: dict[str, int] = field(default_factory=dict)
    # open: перемешанные тексты (только без среза)
    texts: list[str] = field(default_factory=list)
    enps_score: float | None = None
    # срез: {group_key: {"total": n, "distribution": {...}} | "suppressed"}
    groups: dict[str, Any] = field(default_factory=dict)


def _dist_add(dist: dict[str, int], answer_value: dict[str, Any], qtype: str) -> None:
    if qtype == "single":
        opt = answer_value.get("option")
        if isinstance(opt, int):
            dist[str(opt)] = dist.get(str(opt), 0) + 1
    elif qtype == "multi":
        for opt in answer_value.get("options") or []:
            if isinstance(opt, int):
                dist[str(opt)] = dist.get(str(opt), 0) + 1
    elif qtype in ("scale", "enps"):
        val = answer_value.get("value")
        if isinstance(val, int):
            dist[str(val)] = dist.get(str(val), 0) + 1


def enps_from_distribution(dist: dict[str, int]) -> float | None:
    """eNPS = %промоутеров(9-10) − %критиков(0-6)."""
    total = sum(dist.values())
    if total == 0:
        return None
    promoters = sum(c for v, c in dist.items() if v.isdigit() and int(v) >= 9)
    detractors = sum(c for v, c in dist.items() if v.isdigit() and int(v) <= 6)
    return round(100 * (promoters - detractors) / total, 1)


async def question_stats(
    db: AsyncSession,
    survey: Survey,
    question: SurveyQuestion,
    *,
    dimension: str | None,
    k_anonymity: int,
) -> QuestionStats:
    if dimension is not None and dimension not in DIMENSIONS:
        raise ValueError(f"Недопустимое измерение среза: {dimension!r}")

    stats = QuestionStats(
        question_id=question.id,
        qtype=question.qtype,
        prompt=question.prompt,
        total_answers=0,
    )

    dim_col = getattr(SurveyAnswerSet, dimension) if dimension else None
    stmt = (
        select(SurveyAnswer.value, dim_col if dim_col is not None else func.now())
        .join(SurveyAnswerSet, SurveyAnswerSet.id == SurveyAnswer.answer_set_id)
        .where(SurveyAnswer.question_id == question.id)
    )
    if question.qtype == "open":
        # Тексты: без демографии, порядок по random-UUID (не по времени).
        rows = await db.execute(
            select(SurveyAnswer.value)
            .join(SurveyAnswerSet, SurveyAnswerSet.id == SurveyAnswer.answer_set_id)
            .where(SurveyAnswer.question_id == question.id)
            .order_by(SurveyAnswerSet.id)
        )
        for (value,) in rows:
            txt = (value or {}).get("text")
            if isinstance(txt, str) and txt.strip():
                stats.texts.append(txt.strip())
        stats.total_answers = len(stats.texts)
        return stats

    rows = (await db.execute(stmt)).all()
    stats.total_answers = len(rows)

    if dimension is None:
        for value, _ in rows:
            _dist_add(stats.distribution, value or {}, question.qtype)
        if question.qtype == "enps":
            stats.enps_score = enps_from_distribution(stats.distribution)
        return stats

    # Срез по одному измерению.
    grouped: dict[str, list[dict[str, Any]]] = {}
    for value, group_val in rows:
        key = str(group_val) if group_val is not None else "—"
        grouped.setdefault(key, []).append(value or {})

    for key, values in grouped.items():
        if survey.is_anonymous and len(values) < k_anonymity:
            stats.groups[key] = SUPPRESSED
            continue
        dist: dict[str, int] = {}
        for value in values:
            _dist_add(dist, value, question.qtype)
        entry: dict[str, Any] = {"total": len(values), "distribution": dist}
        if question.qtype == "enps":
            entry["enps_score"] = enps_from_distribution(dist)
        stats.groups[key] = entry
    return stats


async def participants_count(db: AsyncSession, survey_id: UUID) -> int:
    from app.models.survey import SurveyParticipation

    return (
        await db.execute(
            select(func.count()).select_from(SurveyParticipation).where(
                SurveyParticipation.survey_id == survey_id
            )
        )
    ).scalar_one()

"""Pydantic-схемы опросов (Ф2)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SurveyCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    kind: str = Field(default="standard", pattern="^(standard|enps|pulse)$")
    is_anonymous: bool = False
    opens_at: datetime | None = None
    closes_at: datetime | None = None

    @field_validator("title")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Название не может быть пустым")
        return v


class SurveyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    kind: str | None = Field(default=None, pattern="^(standard|enps|pulse)$")
    is_anonymous: bool | None = None
    opens_at: datetime | None = None
    closes_at: datetime | None = None


class QuestionBody(BaseModel):
    qtype: str = Field(pattern="^(single|multi|open|scale|enps)$")
    prompt: str = Field(min_length=1, max_length=1000)
    # single/multi: {"options": [...]}; scale: {"min": 1, "max": 5}
    options: dict[str, Any] | None = None
    required: bool = True

    @field_validator("options")
    @classmethod
    def _check_options(cls, v: dict[str, Any] | None, info) -> dict[str, Any] | None:  # noqa: ANN001
        qtype = info.data.get("qtype")
        if qtype in ("single", "multi"):
            opts = (v or {}).get("options")
            if not isinstance(opts, list) or not (2 <= len(opts) <= 20):
                raise ValueError("Нужно от 2 до 20 вариантов ответа")
            if not all(isinstance(o, str) and o.strip() and len(o) <= 500 for o in opts):
                raise ValueError("Варианты — непустые строки до 500 символов")
        if qtype == "scale":
            lo = (v or {}).get("min", 1)
            hi = (v or {}).get("max", 5)
            if not (isinstance(lo, int) and isinstance(hi, int) and 0 <= lo < hi <= 10):
                raise ValueError("Шкала: 0 ≤ min < max ≤ 10")
        return v


class QuestionsReplace(BaseModel):
    questions: list[QuestionBody] = Field(min_length=1, max_length=50)


class QuestionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    qtype: str
    prompt: str
    options: dict[str, Any] | None
    required: bool
    position: int


class SurveyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    audience_id: UUID | None
    title: str
    description: str | None
    kind: str
    is_anonymous: bool
    opens_at: datetime | None
    closes_at: datetime | None
    status: str
    published_at: datetime | None
    created_at: datetime
    questions: list[QuestionResponse] = []
    # Персональное:
    participated: bool = False
    is_open_now: bool = False
    participants: int = 0


class SurveyListResponse(BaseModel):
    items: list[SurveyResponse]
    content_role: str


class SubmitAnswer(BaseModel):
    question_id: UUID
    # single: {"option": i}; multi: {"options": [...]}; open: {"text": ...};
    # scale/enps: {"value": n}
    value: dict[str, Any]


class SubmitBody(BaseModel):
    answers: list[SubmitAnswer] = Field(max_length=100)


class QuestionStatsResponse(BaseModel):
    question_id: UUID
    qtype: str
    prompt: str
    total_answers: int
    distribution: dict[str, int]
    texts: list[str]
    enps_score: float | None
    groups: dict[str, Any]


class SurveyResultsResponse(BaseModel):
    survey_id: UUID
    participants: int
    audience_size: int
    dimension: str | None
    questions: list[QuestionStatsResponse]

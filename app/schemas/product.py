"""Pydantic-схемы ассортимента (Ф4) и витрины."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CategoryBody(BaseModel):
    title: str = Field(min_length=1, max_length=255)

    @field_validator("title")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Название не может быть пустым")
        return v


class CategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    position: int


class ProductLinkBody(BaseModel):
    object_type: str = Field(pattern="^(course|lesson|material)$")
    object_id: UUID


class ProductLinkResponse(ProductLinkBody):
    title: str | None = None
    url_path: str | None = None


class PhotoRef(BaseModel):
    media_id: UUID


class ProductUpsert(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=10_000)
    category_id: UUID | None = None
    photos: list[PhotoRef] | None = Field(default=None, max_length=10)
    composition: str | None = Field(default=None, max_length=10_000)
    allergens: str | None = Field(default=None, max_length=2_000)
    shelf_life: str | None = Field(default=None, max_length=2_000)
    serving: str | None = Field(default=None, max_length=10_000)
    upsell: str | None = Field(default=None, max_length=2_000)
    links: list[ProductLinkBody] | None = Field(default=None, max_length=20)


class ProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    category_id: UUID | None
    audience_id: UUID | None
    title: str
    description: str | None
    composition: str | None
    allergens: str | None
    shelf_life: str | None
    serving: str | None
    upsell: str | None
    status: str
    published_at: datetime | None
    updated_at: datetime
    # Заполняется в API:
    photo_urls: list[str] = []
    links: list[ProductLinkResponse] = []
    viewed_by_me: bool = False


class ProductListResponse(BaseModel):
    categories: list[CategoryResponse]
    items: list[ProductResponse]
    content_role: str


# ─── Витрина (learn_home) ────────────────────────────────────────────────────


class HomeCourse(BaseModel):
    id: UUID
    title: str
    course_type: str
    lessons_total: int
    lessons_completed: int
    due_at: datetime | None


class HomeAck(BaseModel):
    id: UUID
    title: str
    deadline_at: datetime | None


class HomeNovelty(BaseModel):
    object_type: str
    object_id: UUID
    title: str
    url_path: str
    published_at: datetime | None


class HomeSurvey(BaseModel):
    id: UUID
    title: str
    kind: str
    closes_at: datetime | None


class HomeRating(BaseModel):
    points: float
    rank: int | None
    total_participants: int


class HomeAssessment(BaseModel):
    id: UUID
    title: str
    ends_at: datetime | None


class HomeResponse(BaseModel):
    courses: list[HomeCourse]
    pending_acks: list[HomeAck]
    novelties: list[HomeNovelty]
    surveys: list[HomeSurvey]
    rating: HomeRating | None
    assessments: list[HomeAssessment] = []


class LearnProfileResponse(BaseModel):
    profile_id: UUID | None
    full_name: str
    email: str
    avatar_url: str | None
    position_name: str | None
    store_name: str | None
    department_name: str | None
    org_role: str | None
    content_role: str | None
    status_text: str | None
    hired_at: date | None
    tenure_days: int | None

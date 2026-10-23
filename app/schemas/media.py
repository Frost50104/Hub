"""Схемы конвейера видео урока (0066). Write-схемы — `extra="forbid"`: лишний
ключ должен давать 422, а не молчаливый no-op."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

Resolution = Literal["540p", "720p", "1080p"]
RESOLUTIONS: tuple[str, ...] = ("540p", "720p", "1080p")
# Цена Hedra Character-3 за секунду ЗВУКА, центы — сверено с `POST
# /v3/models/hedra-character-3/estimate` 23.10.2026 (540p 2,857¢ за 1 с и далее
# 2,5¢/с; 720p 5¢/с; 1080p 6,4286¢/с; `duration_ms` на цену не влияет — Hedra
# тарифицирует длину аудио, у нас это и есть длина куска). Локальная таблица
# авторитетна, `estimate` Hedra лишь сверяет. Зеркало — `web/src/lib/storyboard.ts`.
HEDRA_CENTS_PER_SEC: dict[str, float] = {"540p": 2.5, "720p": 5.0, "1080p": 6.43}


class CleanupDefaults(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_pause_sec: float = Field(default=1.5, ge=0.5, le=10)
    keep_sec: float = Field(default=0.7, ge=0.2, le=3)
    margin_sec: float = Field(default=0.2, ge=0, le=1)
    denoise: Literal["afftdn", "arnndn", "none"] = "afftdn"
    loudnorm_i: float = Field(default=-16, ge=-30, le=-10)
    loudnorm_tp: float = Field(default=-1.5, ge=-5, le=0)
    loudnorm_lra: float = Field(default=11, ge=1, le=20)
    fps_cap: Literal[24, 25, 30, 60] = 30
    scale_cap: Literal[720, 1080] = 1080


class StoryboardParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    face_ratio_thr: float = Field(default=0.12, ge=0.03, le=0.6)
    min_segment_sec: float = Field(default=4, ge=1, le=60)
    bridge_gap_sec: float = Field(default=2, ge=0, le=30)


class MediaJobOut(BaseModel):
    id: UUID
    media_id: UUID
    kind: str
    status: str
    params: dict[str, Any]
    result: dict[str, Any]
    error: str | None
    attempts: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class SceneTestOut(BaseModel):
    media_id: UUID
    url: str
    created_at: datetime


class MediaAdminSettingsOut(BaseModel):
    enabled: bool
    env_enabled: bool
    avatar_env_enabled: bool
    stt_configured: bool
    auto_transcribe: bool
    scene_media_id: UUID | None
    scene_url: str | None
    scene_test: SceneTestOut | None
    avatar_monthly_minutes_cap: int
    avatar_resolution: Resolution
    cleanup_defaults: CleanupDefaults
    storyboard: StoryboardParams
    glossary: str
    stt_provider: str
    month_used_minutes: float
    active_jobs: int


class MediaAdminSettingsPut(BaseModel):
    """Частичное обновление: присылают только изменённые ключи."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    auto_transcribe: bool | None = None
    scene_media_id: UUID | None = None
    avatar_monthly_minutes_cap: int | None = Field(default=None, ge=0, le=100_000)
    avatar_resolution: Resolution | None = None
    cleanup_defaults: CleanupDefaults | None = None
    storyboard: StoryboardParams | None = None
    glossary: str | None = Field(default=None, max_length=500)


# ─── Сборка из записей, деталь медиа ─────────────────────────────────────────


class MergePart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    media_id: UUID
    trim_start_sec: float = Field(default=0, ge=0)
    trim_end_sec: float | None = Field(default=None, gt=0)


class MergeCreate(BaseModel):
    """2–20 частей с ролью `part` и статусом `ready`, в порядке склейки."""

    model_config = ConfigDict(extra="forbid")

    parts: list[MergePart] = Field(min_length=2, max_length=20)


class JobCreate(BaseModel):
    """`POST /learn/media/{id}/jobs` — запуск или повтор задания по кнопке.
    Виды добавляются по мере инкрементов (`cleanup`, `compose` — позже)."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["transcribe", "cleanup", "analyze", "compose"]
    params: dict[str, Any] | None = None


class TranscriptInfo(BaseModel):
    language: str
    chars: int
    provider: str
    model: str
    updated_at: datetime


class TranscriptOut(TranscriptInfo):
    text: str
    segments: list[dict[str, Any]]
    duration_sec: float | None


class MediaPartOut(BaseModel):
    position: int
    source_media_id: UUID
    trim_start_sec: float
    trim_end_sec: float | None
    file_name: str
    duration_sec: float | None
    status: str


class DerivedMediaOut(BaseModel):
    id: UUID
    kind: str
    variant: str | None
    status: str
    url: str | None
    duration_sec: float | None
    size_bytes: int
    file_name: str
    created_at: datetime


class MediaCapabilities(BaseModel):
    """Что можно заказать для этого файла прямо сейчас (сервер знает про
    конфигурацию и состояние; клиент правил не выводит)."""

    transcribe: bool
    cleanup: bool
    compose: bool


class MediaDetailOut(BaseModel):
    id: UUID
    kind: str
    role: str
    status: str
    file_name: str
    mime: str
    size_bytes: int
    duration_sec: float | None
    # Пока `processing`/`failed` — None: отдача ответила бы 409.
    url: str | None
    variant: str | None
    source_media_id: UUID | None
    created_at: datetime
    parts: list[MediaPartOut]
    derived: list[DerivedMediaOut]
    jobs: list[MediaJobOut]
    capabilities: MediaCapabilities
    # Сводка расшифровки (текст — отдельной ручкой `/transcript`).
    transcript: TranscriptInfo | None = None
    subtitle_url: str | None = None


class MergeOut(BaseModel):
    media: MediaDetailOut
    job: MediaJobOut


# ─── Чистовик, раскадровка, использование ────────────────────────────────────


class CutIn(BaseModel):
    """Отрезок исходной записи, который вырезается целиком (перезапись)."""

    model_config = ConfigDict(extra="forbid")

    s: float = Field(ge=0)
    e: float = Field(gt=0)

    @model_validator(mode="after")
    def _ordered(self) -> CutIn:
        if self.e <= self.s:
            raise ValueError("конец вырезки должен быть позже начала")
        return self


class CleanupOverrides(BaseModel):
    """Параметры заказа чистовика поверх `media_cleanup_defaults` тенанта.
    `min_pause_sec = 0` — паузы не трогать. `cuts` — явный список вырезок
    (перезаписи, выбранные автором); без поля режутся уверенные кандидаты
    `retakes.find_retakes`, пустой список — не режется ничего."""

    model_config = ConfigDict(extra="forbid")

    min_pause_sec: float | None = Field(default=None, ge=0, le=10)
    keep_sec: float | None = Field(default=None, ge=0.2, le=3)
    margin_sec: float | None = Field(default=None, ge=0, le=1)
    denoise: Literal["afftdn", "arnndn", "none"] | None = None
    loudnorm: bool | None = None
    fps_cap: Literal[24, 25, 30, 60] | None = None
    scale_cap: Literal[720, 1080] | None = None
    cuts: list[CutIn] | None = Field(default=None, max_length=500)


class RetakeOut(BaseModel):
    s: float
    e: float
    reason: Literal["marker", "repeat"]
    confidence: Literal["high", "low"]
    marker: str | None
    before: str
    after: str


class RetakesOut(BaseModel):
    """`GET /learn/media/{id}/retakes` — кандидаты на вырезку по транскрипту
    исходника; считается на лету, без транскрипта список пуст."""

    media_id: UUID
    duration_sec: float | None
    transcript: bool
    items: list[RetakeOut]


class StoryboardSegmentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    s: float = Field(ge=0)
    e: float = Field(gt=0)
    kind: Literal["speaker", "screen"]
    mode: Literal["goose", "keep"] | None = None


class StoryboardInsertIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    media_id: UUID
    at: float = Field(ge=0)
    duration: float = Field(gt=0)


class StoryboardPut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segments: list[StoryboardSegmentIn] | None = Field(default=None, max_length=500)
    inserts: list[StoryboardInsertIn] | None = Field(default=None, max_length=100)
    goose_enabled: bool | None = None


class StoryboardOut(BaseModel):
    media_id: UUID
    duration_sec: float | None
    face_track: list[float]
    segments_auto: list[dict[str, Any]]
    segments: list[dict[str, Any]]
    inserts: list[dict[str, Any]]
    goose_enabled: bool
    edited_by: UUID | None
    params: dict[str, Any]
    updated_at: datetime


class UsageLessonOut(BaseModel):
    lesson_id: UUID
    title: str
    course_id: UUID
    course_title: str
    published: bool
    in_progress: int


class UsageOut(BaseModel):
    lessons: list[UsageLessonOut]


# ─── Монтаж (гусь + вставки) ─────────────────────────────────────────────────


class ComposeEstimateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolution: Resolution | None = None


class ComposeEstimateOut(BaseModel):
    goose_enabled: bool
    resolution: Resolution
    goose_seconds: float
    segments: int
    inserts: int
    chunks: int
    billed_seconds: int
    cost_cents: int
    currency: str = "USD"
    monthly_cap_sec: int
    monthly_used_sec: float
    allowed: bool
    reason: str | None = None
    scene_set: bool
    hedra_estimate: dict[str, Any] | None = None

"""Схемы конвейера видео урока (0066). Write-схемы — `extra="forbid"`: лишний
ключ должен давать 422, а не молчаливый no-op."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Resolution = Literal["540p", "720p", "1080p"]
RESOLUTIONS: tuple[str, ...] = ("540p", "720p", "1080p")
# Цена Hedra Character-3 за секунду, центы (документация API, 22.10.2026) —
# локальная таблица авторитетна, `estimate` Hedra лишь сверяет.
HEDRA_CENTS_PER_SEC: dict[str, float] = {"540p": 2.5, "720p": 5.0, "1080p": 6.25}


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

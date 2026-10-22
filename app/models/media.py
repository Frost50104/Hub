"""Конвейер видео урока (0066): очередь заданий, транскрипты, раскадровка,
состав сборки. Сами медиафайлы — `models/course.py::MediaFile`.

Инварианты:
- файл под `media_id` неизменяем после `status='ready'`: чистовик и монтаж —
  всегда новые строки `MediaFile` с `source_media_id`/`variant`; на месте
  меняются только файлы в `processing` (нормализация MOV, сборка из записей),
  которых никто ещё не видел;
- одно активное задание данного вида на медиа (`uq_media_jobs_active`):
  двойной клик получает 409, а не второй рендер;
- очередь без DAG: предусловия («сначала расшифровка») проверяет API при
  постановке, воркер берёт любое `queued` по `priority, created_at`;
- `result` — JSON состояния задания (прогресс, статистика, состояние Hedra по
  кускам): задание `compose` возобновляемо и после рестарта не платит дважды;
- раскадровка — отдельная строка на видео: правки автора переживают закрытие
  шторки и повторные заказы; `segments` — действующая, `segments_auto` — как
  нашёл сервер.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
)
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

# Зеркало CHECK-ограничений миграции 0066 — менять парой.
JOB_KINDS: tuple[str, ...] = (
    "merge",
    "normalize",
    "transcribe",
    "analyze",
    "cleanup",
    "compose",
    "avatar_test",
)
JOB_STATUSES: tuple[str, ...] = ("queued", "running", "done", "failed", "cancelled")
ACTIVE_JOB_STATUSES: tuple[str, ...] = ("queued", "running")
MEDIA_STATUSES: tuple[str, ...] = ("ready", "processing", "failed")
MEDIA_ROLES: tuple[str, ...] = ("content", "part", "insert", "scene")
MEDIA_VARIANTS: tuple[str, ...] = ("cleaned", "composed")

# Чем меньше, тем раньше: человек ждёт нормализацию и сборку прямо сейчас,
# расшифровка фоновая, чистовик и монтаж — заказы по кнопке.
JOB_PRIORITY: dict[str, int] = {
    "merge": 10,
    "normalize": 10,
    "transcribe": 50,
    "analyze": 60,
    "cleanup": 100,
    "compose": 100,
    "avatar_test": 100,
}


class MediaPart(Base):
    """Состав собранного видео: откуда взята часть и с какой подрезкой."""

    __tablename__ = "media_parts"

    merged_media_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("media_files.id", ondelete="CASCADE"),
        primary_key=True,
    )
    position: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    # RESTRICT: часть нельзя удалить из-под собранного файла.
    source_media_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("media_files.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    trim_start_sec: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default=sa_text("0")
    )
    trim_end_sec: Mapped[float | None] = mapped_column(Float, nullable=True)


class MediaTranscript(Base):
    """Расшифровка видео: текст для поиска + сегменты с таймкодами для VTT.

    Отдельно от `media_files`: сегменты часового вебинара — сотни килобайт
    JSONB, а строку медиа читает отдача каждого `<video>` под bypass.
    """

    __tablename__ = "media_transcripts"

    media_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("media_files.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    language: Mapped[str] = mapped_column(
        String(8), nullable=False, default="ru", server_default=sa_text("'ru'")
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    # [{"s": 12.34, "e": 15.9, "t": "…", "w": [[s, e, "слово"], …]?}]
    segments: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    duration_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    # У чистовика — откуда перемаплены таймкоды (аудит, не FK).
    source_transcript_media_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=sa_text("now()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=sa_text("now()"),
        onupdate=sa_text("now()"),
        nullable=False,
    )


class MediaStoryboard(Base):
    """Раскадровка чистовика: где в кадре человек (→ гусь), вставки поверх голоса."""

    __tablename__ = "media_storyboard"

    media_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("media_files.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    # Доля высоты кадра, занятая самым большим лицом, по секундам.
    face_track: Mapped[list[float]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=sa_text("'[]'")
    )
    # [{"s", "e", "kind": "speaker"|"screen"}] — как нашёл сервер.
    segments_auto: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=sa_text("'[]'")
    )
    # Действующая раскадровка; у speaker — "mode": "goose"|"keep".
    segments: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=sa_text("'[]'")
    )
    # [{"media_id", "at", "duration"}] — вставки с role='insert'.
    inserts: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=sa_text("'[]'")
    )
    goose_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=sa_text("true")
    )
    edited_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("shadow_users.employee_id", ondelete="SET NULL"),
        nullable=True,
    )
    params: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=sa_text("'{}'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=sa_text("now()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=sa_text("now()"),
        onupdate=sa_text("now()"),
        nullable=False,
    )


class MediaJob(Base):
    """Задание воркера. Claim — `FOR UPDATE SKIP LOCKED` под bypass, аренда
    `lease_until` продлевается heartbeat'ом; просроченная аренда возвращает
    задание в очередь (`jobs.requeue_expired`)."""

    __tablename__ = "media_jobs"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('merge', 'normalize', 'transcribe', 'analyze', 'cleanup', "
            "'compose', 'avatar_test')",
            name="ck_media_jobs_kind",
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'done', 'failed', 'cancelled')",
            name="ck_media_jobs_status",
        ),
        CheckConstraint("attempts >= 0 AND max_attempts >= 1", name="ck_media_jobs_attempts"),
        Index("ix_media_jobs_media", "media_id", sa_text("created_at DESC")),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    # Вход задания: у `merge` — собранный файл в `processing`, у `compose` — чистовик.
    media_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("media_files.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="queued", server_default=sa_text("'queued'")
    )
    params: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=sa_text("'{}'")
    )
    result: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=sa_text("'{}'")
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=sa_text("0")
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=2, server_default=sa_text("2")
    )
    priority: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=100, server_default=sa_text("100")
    )
    run_after: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa_text("now()")
    )
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=sa_text("false")
    )
    requested_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("shadow_users.employee_id", ondelete="SET NULL"),
        nullable=True,
    )
    # Главный выход (видео); VTT ищется по `source_media_id` + `kind='subtitle'`.
    output_media_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("media_files.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=sa_text("now()"), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

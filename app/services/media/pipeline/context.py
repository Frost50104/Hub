"""Контекст задания для обработчиков: временная папка, прогресс для
heartbeat, отмена, обёртка над ffmpeg с потолком времени и настройки."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.services.media import ffmpeg
from app.services.media.jobs import JobSpec
from app.services.media.probe import Probe, parse_ffprobe


class JobFailed(Exception):
    """Ошибка задания. `final=True` — повторять бессмысленно (нет файла, нет
    места, неверный аргумент); иначе воркер вернёт задание в очередь, пока
    есть попытки."""

    def __init__(self, code: str, message: str = "", *, final: bool = True) -> None:
        super().__init__(f"{code}: {message}" if message else code)
        self.code = code
        self.final = final


class JobCancelled(Exception):
    """Отмена человеком (`cancel_requested`) или остановка воркера."""


@dataclass
class JobResult:
    result: dict[str, Any] = field(default_factory=dict)
    output_media_id: UUID | None = None
    # Доменные записи финала — в транзакции воркера вместе с `jobs.finish`.
    apply: Callable[[AsyncSession], Awaitable[None]] | None = None
    # Что удалить ПОСЛЕ коммита (старый исходник после нормализации на месте).
    cleanup_after_commit: list[Path] = field(default_factory=list)


@dataclass
class JobContext:
    spec: JobSpec
    settings: Settings
    tmp: Path
    cancel: asyncio.Event
    log: Any
    progress: dict[str, Any] = field(default_factory=dict)
    # Записать `progress` в `media_jobs.result` НЕМЕДЛЕННО, не дожидаясь
    # heartbeat: ставит воркер. Нужно платным шагам — `job_id` Hedra обязан
    # лечь в базу сразу после submit, иначе рестарт в окне до heartbeat
    # отправил бы кусок второй раз (идемпотентности у API Hedra нет).
    persist: Callable[[], Awaitable[None]] | None = None

    def set_progress(self, stage: str, pct: int | None = None) -> None:
        self.progress = {"stage": stage, "pct": pct}

    async def persist_now(self) -> None:
        if self.persist is not None:
            await self.persist()

    async def ffmpeg(
        self,
        args: list[str],
        *,
        stage: str,
        duration: float | None,
        pct_offset: float = 0.0,
        pct_scale: float = 1.0,
        capture_stderr: bool = False,
        loglevel: str = "error",
    ) -> str:
        """Запуск ffmpeg с потолком времени от длительности и прогрессом в
        heartbeat. `pct_offset/pct_scale` — доля этого вызова в общем прогрессе
        (сборка из нескольких частей)."""
        if self.cancel.is_set():
            raise JobCancelled()
        self.set_progress(stage, int(pct_offset))

        async def on_progress(p: ffmpeg.Progress) -> None:
            local = p.pct(duration)
            if local is not None:
                self.set_progress(stage, int(min(100, pct_offset + local * pct_scale)))

        try:
            return await ffmpeg.run(
                args,
                bin_path=self.settings.media_ffmpeg_bin,
                timeout_sec=ffmpeg.timeout_for(
                    duration, factor=self.settings.media_ffmpeg_timeout_factor
                ),
                on_progress=on_progress,
                cancel=self.cancel,
                capture_stderr=capture_stderr,
                loglevel=loglevel,
            )
        except ffmpeg.FfmpegError as exc:
            if self.cancel.is_set():
                raise JobCancelled() from None
            raise JobFailed("ffmpeg", str(exc), final=False) from exc

    async def probe(self, path: Path) -> Probe:
        try:
            data = await ffmpeg.probe_json(path, bin_path=self.settings.media_ffprobe_bin)
        except ffmpeg.FfmpegError as exc:
            raise JobFailed("probe_failed", str(exc)) from exc
        return parse_ffprobe(data)


def bound_logger(spec: JobSpec) -> Any:
    return structlog.get_logger("media.worker").bind(
        job_id=str(spec.id), kind=spec.kind, media_id=str(spec.media_id)
    )

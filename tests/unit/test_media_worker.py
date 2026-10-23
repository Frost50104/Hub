"""Воркер конвейера: классификация ошибок, наличие бинарей, таблица обработчиков."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from app.config import get_settings
from app.services.media.jobs import JobSpec
from app.services.media.pipeline.context import JobContext, JobFailed
from app.workers import media as worker


def test_classify_failure_final_vs_retry():
    assert worker.classify_failure(
        JobFailed("no_space", "диск", final=True), attempts=1, max_attempts=2
    ) == ("failed", "no_space: диск")
    assert worker.classify_failure(
        JobFailed("ffmpeg", "код 1", final=False), attempts=1, max_attempts=2
    ) == ("retry", "ffmpeg: код 1")
    # Попытки кончились — финал даже для повторяемой ошибки.
    assert (
        worker.classify_failure(
            JobFailed("ffmpeg", "код 1", final=False), attempts=2, max_attempts=2
        )[0]
        == "failed"
    )
    decision, message = worker.classify_failure(RuntimeError("boom"), attempts=1, max_attempts=2)
    assert decision == "retry" and message == "RuntimeError: boom"
    assert worker.classify_failure(RuntimeError("boom"), attempts=2, max_attempts=2)[0] == "failed"


def test_handlers_cover_all_job_kinds():
    """Каждый вид из CHECK миграции 0066 имеет обработчик — иначе задание
    легло бы в очередь и умерло `kind_not_implemented`."""
    from app.models.media import JOB_KINDS

    assert set(worker.HANDLERS) == set(JOB_KINDS)


def test_ffmpeg_available_checks_both_binaries(monkeypatch):
    class S:
        media_ffmpeg_bin = "ffmpeg"
        media_ffprobe_bin = "ffprobe"

    monkeypatch.setattr(worker.shutil, "which", lambda name: "/bin/x" if name == "ffmpeg" else None)
    assert worker.ffmpeg_available(S()) is False
    monkeypatch.setattr(worker.shutil, "which", lambda name: "/bin/x")
    assert worker.ffmpeg_available(S()) is True


def test_worker_identity_is_bounded():
    ident = worker.worker_identity()
    assert ":" in ident and len(ident) <= 64


def _ctx(kind: str = "compose", params: dict | None = None) -> JobContext:
    spec = JobSpec(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        media_id=uuid.uuid4(),
        kind=kind,
        params=params or {},
        attempts=1,
        max_attempts=2,
        requested_by=None,
    )
    return JobContext(
        spec=spec, settings=get_settings(), tmp=Path("/tmp"), cancel=asyncio.Event(), log=None
    )


def test_hedra_state_survives_stage_change_and_falls_back_to_params():
    """Инцидент 23.10: `set_progress` заменял словарь целиком, на стадии
    `render` состояние кусков пропадало, и после OOM возобновлённое задание
    заново отправляло куски в Hedra (409 ALREADY_EXISTS)."""
    ctx = _ctx()
    chunks = [{"i": 0, "job_id": "job_1", "status": "downloaded", "duration_ms": 19000}]
    ctx.set_progress("goose 1/1", 20)
    ctx.progress["hedra"] = {"chunks": chunks}
    ctx.set_progress("render 1/7", 80)
    assert ctx.progress["hedra"] == {"chunks": chunks}
    assert ctx.progress["stage"] == "render 1/7" and ctx.progress["pct"] == 80
    assert worker._resume_params(ctx)["hedra_state"] == {"chunks": chunks}
    assert worker._failure_result(ctx) == {"hedra": {"chunks": chunks}, "billed_seconds": 19}

    # Попытка упала до первого submit — состояние берётся из params прошлой попытки.
    carried = _ctx(params={"hedra_state": {"chunks": chunks}})
    carried.set_progress("probe", 0)
    assert worker._resume_params(carried)["hedra_state"] == {"chunks": chunks}
    assert worker._failure_result(carried)["billed_seconds"] == 19
    # Без состояния — ничего не переносим, минуты возвращаются.
    bare = _ctx()
    assert worker._resume_params(bare) is None
    assert worker._failure_result(bare) == {"hedra": {}, "billed_seconds": 0}
    assert worker._resume_params(_ctx(kind="cleanup")) is None

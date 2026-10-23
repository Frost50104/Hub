"""Воркер конвейера: классификация ошибок, наличие бинарей, таблица обработчиков."""

from __future__ import annotations

from app.services.media.pipeline.context import JobFailed
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


def test_handlers_cover_implemented_kinds():
    assert set(worker.HANDLERS) == {"normalize", "merge", "transcribe", "cleanup", "analyze"}


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

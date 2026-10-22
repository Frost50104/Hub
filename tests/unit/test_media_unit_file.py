"""Сторож юнита конвейера видео (`ops/systemd/signaris-hub-media.service`):
только жёсткий потолок памяти, низкий приоритет CPU, SIGTERM главному
процессу, staging-вариант собирается без прод-путей."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UNIT = ROOT / "ops" / "systemd" / "signaris-hub-media.service"


def _directives() -> list[str]:
    lines: list[str] = []
    for raw in UNIT.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            lines.append(line)
    return lines


def test_memory_is_a_hard_ceiling_only():
    directives = _directives()
    assert not any(d.startswith("MemoryHigh=") for d in directives)
    assert any(d.startswith("MemoryMax=") for d in directives)
    assert "OOMScoreAdjust=600" in directives
    assert not any(d.startswith("WatchdogSec=") for d in directives)


def test_low_priority_and_graceful_stop():
    directives = _directives()
    for expected in (
        "CPUWeight=20",
        "Nice=10",
        "KillMode=mixed",
        "TimeoutStopSec=30",
        "Restart=always",
        "LimitCORE=0",
        "Environment=PYTHONFAULTHANDLER=1",
        "ExecStart=/opt/signaris-hub/.venv/bin/python -m app.workers.media",
    ):
        assert expected in directives, expected


def test_staging_unit_builds_without_prod_paths():
    spec = importlib.util.spec_from_file_location(
        "make_staging_unit", ROOT / "ops" / "systemd" / "make-staging-unit.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    staging = module.build(UNIT.read_text(encoding="utf-8"), "5059", "5060")
    assert "/opt/signaris-hub-staging/.env" in staging
    assert "WorkingDirectory=/opt/signaris-hub-staging" in staging
    assert "-m app.workers.media" in staging

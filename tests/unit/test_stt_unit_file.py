"""Сторож конфигурации юнита распознавания речи (`ops/systemd/signaris-hub-stt.service`).

Юнит ставится руками (scp), и каждая строка ниже — след инцидента 09.09–21.10
(docs/tech-debt/incidents.md): вернись `MemoryHigh` — вернётся вечное
торможение без OOM; пропади сторож или `--workers 1` — зависание снова будет
молчать или юнит начнут убивать каждую минуту.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UNIT = ROOT / "ops" / "systemd" / "signaris-hub-stt.service"


def _directives() -> list[str]:
    lines: list[str] = []
    joined = ""
    for raw in UNIT.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        joined += line.rstrip("\\").strip() + " "
        if not line.endswith("\\"):
            lines.append(joined.strip())
            joined = ""
    return lines


def test_no_memory_high_only_a_hard_ceiling():
    directives = _directives()
    assert not any(d.startswith("MemoryHigh=") for d in directives)
    assert any(d.startswith("MemoryMax=") for d in directives)
    assert "OOMScoreAdjust=500" in directives


def test_watchdog_is_on_and_dumps_stacks_without_core():
    directives = _directives()
    for expected in (
        "WatchdogSec=60",
        "NotifyAccess=main",
        "Environment=PYTHONFAULTHANDLER=1",
        "LimitCORE=0",
        "TimeoutAbortSec=10",
        "TimeoutStopSec=15",
        "Restart=always",
    ):
        assert expected in directives, expected


def test_model_comes_only_from_cache():
    assert "Environment=HF_HUB_OFFLINE=1" in _directives()


def test_single_process_so_pings_are_accepted():
    """С `--workers` > 1 пингуют дети, а `NotifyAccess=main` их отбрасывает."""
    exec_start = next(d for d in _directives() if d.startswith("ExecStart="))
    assert "--workers 1" in exec_start
    assert "--timeout-graceful-shutdown" in exec_start


def test_staging_unit_still_builds_without_prod_paths():
    spec = importlib.util.spec_from_file_location(
        "make_staging_unit", ROOT / "ops" / "systemd" / "make-staging-unit.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    staging = module.build(UNIT.read_text(encoding="utf-8"), "5071", "5072")
    assert "--port 5072" in staging
    assert "/opt/signaris-hub-staging/.env" in staging

"""Проверка распознавания речи после деплоя: юнит жив, модель загружена,
настоящая запись расшифровывается.

Зовёт `deploy/deploy.sh` после рестарта юнита — только если юнит активен
(staging без STT не проверяется). Ждёт `/health` = `ready` до 90 с, шлёт
`ops/stt/smoke-ru.webm` (синтетическая команда «Поставь задачу на пятницу…»)
и требует непустой текст. Печатает время и память юнита: так на каждом выкате
видно, что голос жив, а `MemoryMax` держит. До 21.10 такой проверки не было, и
STT шесть недель висел незамеченным (docs/tech-debt/incidents.md).

    cd /opt/signaris-hub && .venv/bin/python -m app.jobs.stt_smoke --unit signaris-hub-stt.service

Код возврата: 0 — работает, 1 — нет (деплой печатает WARNING и не падает).
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import httpx
import structlog

from app import log as log_config
from app.config import get_settings

log = structlog.get_logger("jobs.stt_smoke")

SAMPLE = Path(__file__).resolve().parents[2] / "ops" / "stt" / "smoke-ru.webm"
READY_WAIT_SEC = 90.0


def unit_memory_mb(unit: str, root: Path = Path("/sys/fs/cgroup/system.slice")) -> dict[str, int]:
    out: dict[str, int] = {}
    for name in ("current", "peak"):
        try:
            raw = (root / unit / f"memory.{name}").read_text().split()[0]
            out[f"{name}_mb"] = round(int(raw) / 1024 / 1024)
        except (OSError, ValueError, IndexError):
            pass
    return out


def wait_ready(client: httpx.Client, base: str, *, deadline: float) -> str:
    """Статус `/health`, как только он окончательный, или последний до срока."""
    status = "unreachable"
    while True:
        try:
            resp = client.get(f"{base}/health")
            status = str(resp.json().get("status"))
        except (httpx.HTTPError, ValueError, AttributeError):
            status = "unreachable"
        if status in ("ready", "missing", "error", "disabled") or time.monotonic() >= deadline:
            return status
        time.sleep(2)


def run(unit: str) -> int:
    settings = get_settings()
    base = settings.stt_url.rstrip("/")
    with httpx.Client(timeout=10) as client:
        status = wait_ready(client, base, deadline=time.monotonic() + READY_WAIT_SEC)
        if status != "ready":
            log.error("stt.smoke_failed", reason=f"health={status}")
            return 1
        started = time.monotonic()
        try:
            resp = client.post(
                f"{base}/transcribe",
                content=SAMPLE.read_bytes(),
                headers={"Content-Type": "audio/webm"},
                timeout=settings.stt_timeout_sec,
            )
        except httpx.HTTPError as e:
            log.error("stt.smoke_failed", reason=type(e).__name__)
            return 1
        try:
            text = str(resp.json().get("text") or "").strip()
        except (ValueError, AttributeError):
            text = ""
        if resp.status_code != 200 or not text:
            log.error("stt.smoke_failed", reason=f"http={resp.status_code}", text_chars=len(text))
            return 1
        log.info(
            "stt.smoke_ok",
            seconds=round(time.monotonic() - started, 1),
            text_chars=len(text),
            **unit_memory_mb(unit),
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--unit", default="signaris-hub-stt.service")
    args = parser.parse_args()
    log_config.configure()
    return run(args.unit)


if __name__ == "__main__":
    raise SystemExit(main())

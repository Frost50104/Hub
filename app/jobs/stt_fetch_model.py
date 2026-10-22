"""Скачать веса модели распознавания речи в кэш юнита signaris-hub-stt.

Юнит грузит модель ТОЛЬКО из кэша (`HF_HUB_OFFLINE=1`): скачивание внутри его
процесса 09.09 оставило ~230 МБ памяти сверху и повесило юнит на шесть недель
(docs/tech-debt/incidents.md). Это задание — единственный путь, которым веса
попадают на сервер: новый сервер, смена `SIGNARIS_HUB_STT_MODEL`, битый кэш.

Каталог — `SIGNARIS_HUB_STT_CACHE_DIR`, тот же, что читает юнит; без него
задание отказывается работать (веса легли бы в `~/.cache`, а сервис так и
отвечал бы «не настроено»). Скачивание идёт обычным HTTP, без hf_xet: xet
держит в памяти до десяти кусков по ~61 МБ. Запускать от пользователя юнита
и с потолком памяти:

    systemd-run --wait --pipe --uid=signaris -p MemoryMax=1G \\
      -p EnvironmentFile=/opt/signaris-hub/.env -p WorkingDirectory=/opt/signaris-hub \\
      /opt/signaris-hub/.venv/bin/python -m app.jobs.stt_fetch_model

После — `systemctl restart signaris-hub-stt`: модель грузится при старте юнита.
"""

from __future__ import annotations

import os

import structlog

log = structlog.get_logger("jobs.stt_fetch_model")


def main() -> int:
    # До импорта huggingface_hub: он читает переменные один раз, при импорте.
    os.environ["HF_HUB_DISABLE_XET"] = "1"
    # Задание обязано идти в сеть, даже если его запустили с окружением юнита.
    os.environ["HF_HUB_OFFLINE"] = "0"

    from app import log as log_config
    from app.config import get_settings

    log_config.configure()
    settings = get_settings()
    if not settings.stt_cache_dir:
        log.error(
            "stt.fetch_needs_cache_dir",
            hint="задайте SIGNARIS_HUB_STT_CACHE_DIR — тот же каталог, что читает юнит",
        )
        return 2

    from faster_whisper import download_model

    path = download_model(settings.stt_model, cache_dir=settings.stt_cache_dir)
    log.info("stt.model_fetched", model=settings.stt_model, path=str(path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

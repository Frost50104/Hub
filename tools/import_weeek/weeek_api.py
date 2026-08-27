"""Клиент публичного API WEEEK с кэшем на диске. Только локально.

Кэш здесь не оптимизация, а страховка: ссылки на вложения WEEEK подписаны
примерно на сутки, а полный обход деталей 16 703 задач идёт минутами. Один
раз выгрузили — дальше пересобираем bundle сколько угодно раз без сети,
правя маппинг.

Токен читается ТОЛЬКО из окружения `WEEEK_API_TOKEN`: аргументом командной
строки он осел бы в истории шелла, в файле — в git.

    export WEEEK_API_TOKEN=…
    python -m tools.import_weeek.fetch --all
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx

BASE_URL = "https://api.weeek.net/public/v1"
DEFAULT_CACHE = Path(".weeek-cache")
PAGE_SIZE = 1000
# 429/5xx: пауза 2, 4, 8, 16 с. Больше четырёх попыток смысла нет — если API
# лежит, лучше остановиться и продолжить позже: кэш уже сохранён.
RETRIES = 4


class WeeekError(RuntimeError):
    pass


class WeeekClient:
    def __init__(self, *, cache: Path = DEFAULT_CACHE, concurrency: int = 8) -> None:
        token = os.environ.get("WEEEK_API_TOKEN", "").strip()
        if not token:
            raise SystemExit(
                "Нужен токен: export WEEEK_API_TOKEN=… (в файлы репозитория он не пишется)"
            )
        self.cache = cache
        self.concurrency = concurrency
        self._client = httpx.Client(
            base_url=BASE_URL,
            headers={"Authorization": f"Bearer {token}"},
            timeout=httpx.Timeout(60.0),
        )
        for sub in ("list", "tasks", "files"):
            (cache / sub).mkdir(parents=True, exist_ok=True)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> WeeekClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # ─── низкий уровень ─────────────────────────────────────────────────────

    def _request(self, path: str, params: dict[str, Any] | None = None) -> dict:
        last: Exception | None = None
        for attempt in range(RETRIES):
            try:
                response = self._client.get(path, params=params)
                if response.status_code in (429, 500, 502, 503, 504):
                    raise WeeekError(f"{response.status_code} на {path}")
                response.raise_for_status()
                payload = response.json()
            except Exception as exc:  # noqa: BLE001 — ретраим любую сетевую беду
                last = exc
                time.sleep(2 ** (attempt + 1))
                continue
            if not payload.get("success", True):
                raise WeeekError(f"{path}: {payload.get('message') or payload.get('errors')}")
            return payload
        raise WeeekError(f"{path}: не удалось за {RETRIES} попыток ({last})")

    def _cached(self, name: str, fetch) -> dict:  # noqa: ANN001
        path = self.cache / name
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        payload = fetch()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return payload

    # ─── справочники ────────────────────────────────────────────────────────

    def projects(self) -> list[dict]:
        return self._cached("list/projects.json", lambda: self._request("/tm/projects"))["projects"]

    def portfolios(self) -> list[dict]:
        payload = self._cached("list/portfolios.json", lambda: self._request("/tm/portfolios"))
        return payload.get("data") or []

    def members(self) -> list[dict]:
        return self._cached("list/members.json", lambda: self._request("/ws/members"))["members"]

    def boards(self, project_id: int) -> list[dict]:
        payload = self._cached(
            f"list/boards-{project_id}.json",
            lambda: self._request("/tm/boards", {"projectId": project_id}),
        )
        return payload.get("boards") or []

    def board_columns(self, board_id: int) -> list[dict]:
        payload = self._cached(
            f"list/columns-{board_id}.json",
            lambda: self._request("/tm/board-columns", {"boardId": board_id}),
        )
        return payload.get("boardColumns") or []

    # ─── задачи ─────────────────────────────────────────────────────────────

    def all_tasks(self) -> list[dict]:
        """Полный список задач воркспейса. `all=1` включает выполненные."""
        path = self.cache / "tasks/all.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        tasks: list[dict] = []
        offset = 0
        while True:
            payload = self._request(
                "/tm/tasks", {"perPage": PAGE_SIZE, "offset": offset, "all": 1}
            )
            batch = payload.get("tasks") or []
            tasks.extend(batch)
            if not payload.get("hasMore") or not batch:
                break
            offset += len(batch)
        path.write_text(json.dumps(tasks, ensure_ascii=False), encoding="utf-8")
        return tasks

    def task_detail(self, task_id: int) -> dict:
        """Одна задача целиком. Нужна ТОЛЬКО ради `attachments[]` — в списочной
        ручке этого поля нет."""
        payload = self._cached(
            f"tasks/{task_id}.json", lambda: self._request(f"/tm/tasks/{task_id}")
        )
        return payload.get("task") or {}

    def task_details(self, task_ids: list[int], *, on_progress=None) -> Iterator[dict]:  # noqa: ANN001
        """Детали пачкой, в несколько потоков. Каждый ответ сразу в кэш —
        обрыв на середине не стоит ничего."""
        done = 0
        with ThreadPoolExecutor(self.concurrency) as pool:
            for detail in pool.map(self.task_detail, task_ids):
                done += 1
                if on_progress and done % 500 == 0:
                    on_progress(done, len(task_ids))
                yield detail

    # ─── файлы ──────────────────────────────────────────────────────────────

    def download(self, url: str, attachment_id: str) -> Path | None:
        """Скачать вложение в кэш. Ссылка подписана и работает без токена.

        Возвращает путь или None, если файл недоступен (подпись протухла,
        файл удалён) — это не повод ронять сборку, имя уйдёт в описание.
        """
        dest = self.cache / "files" / attachment_id
        if dest.exists() and dest.stat().st_size > 0:
            return dest
        for attempt in range(RETRIES):
            try:
                with httpx.stream("GET", url, timeout=120.0, follow_redirects=True) as r:
                    if r.status_code >= 400:
                        raise WeeekError(str(r.status_code))
                    tmp = dest.with_suffix(".part")
                    with tmp.open("wb") as fh:
                        for chunk in r.iter_bytes(64 * 1024):
                            fh.write(chunk)
                    tmp.replace(dest)
                return dest
            except Exception:  # noqa: BLE001
                if attempt == RETRIES - 1:
                    return None
                time.sleep(2 ** (attempt + 1))
        return None

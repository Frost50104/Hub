"""Выгрузка WEEEK в локальный кэш. Первый шаг переноса.

    export WEEEK_API_TOKEN=…
    python -m tools.import_weeek.fetch            # справочники + список задач
    python -m tools.import_weeek.fetch --details  # + детали каждой задачи

Детали (`/tm/tasks/{id}`) нужны ради `attachments[]` — в списочной ручке
вложений нет. Тянем их для ВСЕХ задач объёма, а не только открытых: у
выполненных имена файлов уходят в описание, чтобы человек знал, что было
приложено.

Всё складывается в `.weeek-cache/`; повторный запуск ничего не перекачивает.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from tools.import_weeek.mapping import select_projects, select_tasks
from tools.import_weeek.weeek_api import DEFAULT_CACHE, WeeekClient


def main() -> int:
    parser = argparse.ArgumentParser(description="Выгрузить WEEEK в локальный кэш")
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--details", action="store_true", help="тянуть детали задач")
    parser.add_argument("--concurrency", type=int, default=8)
    args = parser.parse_args()

    started = time.time()
    with WeeekClient(cache=args.cache, concurrency=args.concurrency) as api:
        projects = api.projects()
        portfolios = api.portfolios()
        members = api.members()
        print(f"справочники: проектов {len(projects)}, портфелей {len(portfolios)}, "
              f"участников {len(members)}")

        boards_total = columns_total = 0
        for project in projects:
            boards = api.boards(int(project["id"]))
            boards_total += len(boards)
            for board in boards:
                columns_total += len(api.board_columns(int(board["id"])))
        print(f"доски: {boards_total}, колонок: {columns_total}")

        tasks = api.all_tasks()
        scope_projects = select_projects(projects, tasks)
        scope_tasks = select_tasks(tasks, scope_projects)
        done = sum(1 for t in scope_tasks if t.get("isCompleted"))
        print(f"задач всего: {len(tasks)}")
        print(f"ОБЪЁМ: проектов {len(scope_projects)}, задач {len(scope_tasks)} "
              f"(открытых {len(scope_tasks) - done}, выполненных {done})")

        if not args.details:
            print("\nДетали не тянули. Повторите с --details, чтобы забрать вложения.")
            return 0

        ids = [int(t["id"]) for t in scope_tasks]
        cached = sum(1 for i in ids if (args.cache / f"tasks/{i}.json").exists())
        print(f"\nдетали задач: {cached} уже в кэше, тяну {len(ids) - cached}…")

        def progress(done_now: int, total: int) -> None:
            rate = done_now / max(time.time() - started, 1e-6)
            print(f"  {done_now}/{total}  ({rate:.0f} задач/с)", flush=True)

        with_attachments = files = 0
        for detail in api.task_details(ids, on_progress=progress):
            attachments = detail.get("attachments") or []
            if attachments:
                with_attachments += 1
                files += len(attachments)
        print(f"готово за {time.time() - started:.0f}с: задач с вложениями "
              f"{with_attachments}, файлов {files}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

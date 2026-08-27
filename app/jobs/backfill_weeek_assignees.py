"""Проход 2 переноса из WEEEK: доставить исполнителей, когда люди появятся.

На момент импорта в Hub было пятеро из 41 участника WEEEK, а назначить
исполнителем можно только того, кто уже заходил (`task_assignees.employee_id` —
FK на `shadow_users`). Остальным проход 1 вписал в описание строку
«_Исполнитель в WEEEK: Имя_». Эта джоба находит тех, кто с тех пор зашёл,
проставляет их исполнителями и снимает строку.

    cd /opt/signaris-hub && sudo -u signaris .venv/bin/python \
        -m app.jobs.backfill_weeek_assignees --bundle ./weeek-bundle \
        --tenant-slug uppetit --actor-email pp@uppetit.ru [--apply]

Идемпотентна: гонять можно сколько угодно раз по мере того, как люди заходят.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from pathlib import Path
from uuid import UUID

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import log as log_config
from app.db import tenant_scoped_session
from app.jobs.import_weeek_bundle import resolve_tenant_and_actor
from app.jobs.weeek_common import (
    KIND_TASK,
    assignee_note,
    compose_description,
    hub_id,
    notes_for,
    strip_assignee_note,
)
from app.models.shadow import ShadowUser
from app.models.task import Task, TaskAssignee
from app.services.project_access import ensure_project_member
from app.services.task_assignees import apply_assignee_side_effects, set_task_assignees

log = structlog.get_logger("jobs.backfill_weeek_assignees")

COMMIT_EVERY = 200


class Backfill:
    def __init__(self, bundle: Path, *, tenant_id: UUID, actor_id: UUID, apply: bool) -> None:
        self.bundle = bundle
        self.tenant_id = tenant_id
        self.actor_id = actor_id
        self.apply = apply
        self.stats: Counter = Counter()
        self.still_missing: Counter = Counter()
        self.people: dict[str, UUID] = {}

    def bump(self, key: str, delta: int = 1) -> None:
        self.stats[key] += delta

    async def load_people(self, db: AsyncSession) -> None:
        rows = await db.execute(
            select(func.lower(ShadowUser.email), ShadowUser.employee_id).where(
                ShadowUser.deleted_at.is_(None)
            )
        )
        self.people = {e: i for e, i in rows.all() if e}

    async def process(self, db: AsyncSession, row: dict) -> None:
        wanted: list[UUID] = []
        missing: list[str] = []
        for person in row.get("assignees") or []:
            email = (person.get("email") or "").lower()
            employee_id = self.people.get(email)
            if employee_id is None:
                missing.append(person.get("name") or email)
                self.still_missing[email] += 1
            elif employee_id not in wanted:
                wanted.append(employee_id)
        if not wanted:
            self.bump("пропущено: людей всё ещё нет")
            return

        task = await db.get(Task, hub_id(self.tenant_id, KIND_TASK, row["weeek_id"]))
        if task is None:
            self.bump("пропущено: задача не переносилась")
            return
        already = await db.execute(
            select(TaskAssignee.employee_id).where(TaskAssignee.task_id == task.id).limit(1)
        )
        if already.first() is not None:
            # Гейт идемпотентности и заодно защита от затирания: у
            # `set_task_assignees` replace-семантика, и ручное назначение
            # исчезло бы.
            self.bump("пропущено: исполнитель уже есть")
            return

        self._clean_description(task, row, missing)

        diff = await set_task_assignees(
            db, task=task, employee_ids=wanted, actor_id=self.actor_id
        )
        if not task.done:
            # notify=False обязателен: иначе уйдёт пачка «Вам назначена
            # задача» про задачи 2022 года. record=False — лента задачи
            # начинается с «создана», события «назначен» тут не было.
            await apply_assignee_side_effects(
                db, task=task, diff=diff, actor_id=self.actor_id, actor_name="",
                notify=False, record=False,
            )
        else:
            # У выполненной задачи наблюдатель не нужен — только доступ.
            for employee_id in diff.added:
                await ensure_project_member(
                    db,
                    project_id=task.project_id,
                    tenant_id=task.tenant_id,
                    employee_id=employee_id,
                    added_by=self.actor_id,
                )
        self.bump("исполнителей проставлено", len(diff.added))
        self.bump("задач обновлено")

    def _clean_description(self, task: Task, row: dict, missing: list[str]) -> None:
        """Снять строку «Исполнитель в WEEEK: …», не тронув ручных правок."""
        parent_note, attach_note = notes_for(row, self.tenant_id)
        original_names = [
            p.get("name") or (p.get("email") or "") for p in (row.get("assignees") or [])
        ]
        expected = compose_description(
            row.get("body_md"),
            weeek_id=int(row["weeek_id"]),
            parent_note=parent_note,
            attachments_note=attach_note,
            assignee_note_text=assignee_note(original_names),
        )
        clean = compose_description(
            row.get("body_md"),
            weeek_id=int(row["weeek_id"]),
            parent_note=parent_note,
            attachments_note=attach_note,
            assignee_note_text=assignee_note(missing),
        )
        if task.description == expected:
            task.description = clean
            self.bump("описаний очищено")
            return
        stripped, removed = strip_assignee_note(task.description)
        if removed:
            # Описание правили руками, но сноска на месте — снимаем только её.
            task.description = compose_description(
                stripped,
                weeek_id=int(row["weeek_id"]),
                assignee_note_text=assignee_note(missing),
            ) if missing else stripped
            self.bump("описаний очищено после ручной правки")
        else:
            self.bump("описаний не тронуто (переписаны вручную)")

    async def run(self, db: AsyncSession) -> None:
        manifest = json.loads((self.bundle / "manifest.json").read_text(encoding="utf-8"))
        await self.load_people(db)
        pending = 0
        for spec in manifest["projects"]:
            payload = json.loads((self.bundle / spec["tasks_file"]).read_text(encoding="utf-8"))
            for row in payload["tasks"]:
                if not row.get("assignees"):
                    continue
                await self.process(db, row)
                pending += 1
                if pending % COMMIT_EVERY == 0:
                    await self._finish(db)
        await self._finish(db)

    async def _finish(self, db: AsyncSession) -> None:
        if self.apply:
            await db.commit()
        else:
            await db.flush()


async def main() -> int:
    log_config.configure()
    parser = argparse.ArgumentParser(description="Доставить исполнителей после переноса WEEEK")
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--tenant-slug", default="uppetit")
    parser.add_argument("--actor-email", required=True)
    parser.add_argument("--apply", action="store_true", help="записать (по умолчанию разбор)")
    args = parser.parse_args()

    tenant_id, actor_id = await resolve_tenant_and_actor(args.tenant_slug, args.actor_email)
    job = Backfill(args.bundle, tenant_id=tenant_id, actor_id=actor_id, apply=args.apply)
    async with tenant_scoped_session(tenant_id) as db:
        await job.run(db)
        if not args.apply:
            await db.rollback()

    log.info("weeek_assignees.summary", applied=args.apply, **dict(job.stats))
    for email, count in job.still_missing.most_common():
        log.info("weeek_assignees.still_missing", email=email, tasks=count)
    if not args.apply:
        log.info("weeek_assignees.dry_run", hint="повторите с --apply, чтобы записать")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

"""One-shot: перенос задач из WEEEK в Hub. Проход 1.

Bundle готовит локальный инструмент `tools/import_weeek/` — здесь ни сети, ни
токена, ни разбора HTML: джоба только пишет в базу и на диск.

    cd /opt/signaris-hub && sudo -u signaris .venv/bin/python \
        -m app.jobs.import_weeek_bundle --bundle ./weeek-bundle \
        --tenant-slug uppetit --actor-email pp@uppetit.ru [--apply]

По умолчанию — разбор (вся работа и `rollback`), запись по `--apply`.

## Почему мимо `create_task_record`

Сервис обязан делать две вещи, которые для переноса архива неверны:

1. `ensure_watcher(reason="creator")` на КАЖДОЙ задаче. На 16 703 задачах
   актёр становится наблюдателем всего: любой чужой комментарий и любая
   отметка «выполнено» шлют ему пуш. Удалять watcher'ов постфактум — значит
   оставить окно, в которое может попасть падение; правильно не создавать.
2. `set_done` ставит `datetime.now(UTC)`, а у 14 035 задач есть настоящая дата
   закрытия за 2022–2026.

Плюс цена: 8–10 round-trip'ов на задачу против пачки на 500 строк.

Что теряется вместе с сервисом и чем заменено — таблица в плане переноса и
проверки в `tests/integration/test_import_weeek.py`. Каждая замена там своим
тестом: подзадача ровно одного уровня, этап своего проекта, `seq` внутри
`next_task_seq`, `done` в паре с `completed_at`, ноль creator-watcher'ов,
ноль уведомлений.

Идемпотентность — на детерминированных id (`weeek_common.hub_id`): повторный
запуск видит строку по первичному ключу и пропускает её. Файла состояния нет,
состояние — сама база.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import structlog
from signaris_auth import Principal
from sqlalchemy import func, insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app import log as log_config
from app.db import tenant_scoped_session
from app.jobs.weeek_common import (
    KIND_ATTACHMENT,
    KIND_CUSTOM_FIELD,
    KIND_FOLDER,
    KIND_PROJECT,
    KIND_STAGE,
    KIND_TASK,
    assignee_note,
    compose_description,
    hub_id,
    notes_for,
)
from app.models.attachment import TaskAttachment
from app.models.custom_field import CustomFieldDefinition, TaskCustomFieldValue
from app.models.project import Project, ProjectMember
from app.models.project_folder import ProjectFolder
from app.models.shadow import ShadowTenant, ShadowUser
from app.models.stage import ProjectStage
from app.models.task import Task, TaskAssignee, TaskWatcher
from app.services.activity_writer import record_activities
from app.services.attachments import (
    ALLOWED_MIME,
    SNIFF_HEAD_BYTES,
    absolute_path,
    resolve_mime,
    sniff_mismatch,
    storage_key_for,
)
from app.services.taskdates import due_noon_utc

log = structlog.get_logger("jobs.import_weeek_bundle")

CHUNK = 500
# Участники команд WEEEK — редакторы, а не смотрители: это рабочие проекты,
# а viewer может менять только статус СВОЕЙ задачи.
TEAM_ROLE = "editor"


@dataclass
class ProjectCtx:
    project_id: UUID
    stage_ids: dict[str, UUID]
    field_ids: dict[str, UUID] = field(default_factory=dict)


class Importer:
    def __init__(
        self, bundle: Path, *, tenant_id: UUID, actor_id: UUID, apply: bool
    ) -> None:
        self.bundle = bundle
        self.tenant_id = tenant_id
        self.actor_id = actor_id
        self.apply = apply
        self.stats: Counter = Counter()
        self.people: dict[str, UUID] = {}

    def bump(self, key: str, delta: int = 1) -> None:
        self.stats[key] += delta

    def _id(self, kind: str, key: str | int) -> UUID:
        return hub_id(self.tenant_id, kind, key)

    async def _finish(self, db: AsyncSession) -> None:
        """Граница шага: коммит при `--apply`, иначе только flush.

        В разборе откатываться ПО ХОДУ нельзя: следующий чанк ссылается на
        проект, этапы и родительские задачи, которых после rollback уже нет.
        Поэтому разбор держит одну транзакцию и откатывает её в самом конце
        (`run`), а все проверки базы — FK, CHECK, отложенные UNIQUE — при этом
        честно отрабатывают.
        """
        if not self.apply:
            await db.flush()
            return
        await db.commit()
        # Identity map иначе держала бы ORM-объекты всех 47 проектов и их
        # структуры до конца прогона.
        db.expunge_all()

    # ─── подготовка ─────────────────────────────────────────────────────────

    async def load_people(self, db: AsyncSession) -> None:
        rows = await db.execute(
            select(func.lower(ShadowUser.email), ShadowUser.employee_id).where(
                ShadowUser.deleted_at.is_(None)
            )
        )
        self.people = {email: employee_id for email, employee_id in rows.all() if email}
        self.bump("людей в Hub", len(self.people))

    async def assert_tenant_scope(self, db: AsyncSession) -> None:
        """RLS-скоуп сессии обязан совпасть с тем тенантом, в который пишем.

        Проверка дешёвая, а цена ошибки — 16 703 задачи в чужой организации:
        `assert_assignees_in_tenant` мы заменили своим резолвом, и «не тот
        тенант» больше некому поймать.
        """
        current = (await db.execute(text("SELECT current_setting('app.tenant_id', true)"))).scalar()
        if str(current) != str(self.tenant_id):
            raise SystemExit(f"сессия скоупится на {current}, а пишем в {self.tenant_id}")

    async def taken_keys(self, db: AsyncSession) -> set[str]:
        rows = await db.execute(select(Project.key))
        return {k for (k,) in rows.all()}

    # ─── папки ──────────────────────────────────────────────────────────────

    async def ensure_folders(self, db: AsyncSession, folders: list[dict]) -> dict[str, UUID]:
        """Портфели WEEEK → папки проектов.

        Сопоставление по ИМЕНИ, а не по детерминированному id: «Отдел
        Маркетинга» человек мог завести руками, и второй такой же в сайдбаре
        выглядел бы поломкой.
        """
        rows = await db.execute(select(ProjectFolder.id, func.lower(ProjectFolder.name)))
        existing = {name: fid for fid, name in rows.all()}
        out: dict[str, UUID] = {}
        for spec in folders:
            name = (spec["name"] or "").strip()
            key = name.lower()
            if key in existing:
                out[spec["weeek_id"]] = existing[key]
                continue
            folder_id = self._id(KIND_FOLDER, spec["weeek_id"])
            db.add(
                ProjectFolder(
                    id=folder_id,
                    tenant_id=self.tenant_id,
                    name=name[:255],
                    position=int(spec.get("position") or 0),
                    created_by=self.actor_id,
                )
            )
            existing[key] = folder_id
            out[spec["weeek_id"]] = folder_id
            self.bump("папок создано")
        await db.flush()
        return out

    # ─── структура проекта ──────────────────────────────────────────────────

    async def ensure_project(
        self, db: AsyncSession, spec: dict, folder_ids: dict[str, UUID], taken: set[str]
    ) -> tuple[Project, bool]:
        project_id = self._id(KIND_PROJECT, spec["weeek_id"])
        existing = await db.get(Project, project_id)
        if existing is not None:
            self.bump("проектов уже было")
            return existing, False

        key = self._allocate_key(spec["key_hint"], taken)
        folder_id = None
        if spec.get("folder_key"):
            folder_id = folder_ids.get(spec["folder_key"])
            # FK не проверяет тенант (RI-триггеры Postgres обходят RLS) —
            # единственная защита в том, что папку мы читаем ЭТОЙ ЖЕ
            # tenant-scoped сессией.
            if folder_id is not None and await db.get(ProjectFolder, folder_id) is None:
                folder_id = None
        project = Project(
            id=project_id,
            tenant_id=self.tenant_id,
            key=key,
            name=spec["name"],
            description=spec.get("description"),
            folder_id=folder_id,
            created_by=self.actor_id,
            # Номера задач выданы сборщиком (1..max_seq). Ставим счётчик СРАЗУ,
            # до вставки задач: если кто-то заведёт задачу через UI посреди
            # импорта, он получит номер выше нашего диапазона, а не столкнётся
            # с UNIQUE (project_id, seq).
            next_task_seq=int(spec["max_seq"]) + 1,
        )
        db.add(project)
        db.add(
            ProjectMember(
                tenant_id=self.tenant_id,
                project_id=project_id,
                employee_id=self.actor_id,
                role="owner",
                added_by=self.actor_id,
            )
        )
        await db.flush()
        self.bump("проектов создано")
        return project, True

    def _allocate_key(self, hint: str, taken: set[str]) -> str:
        base = (hint or "PROJ")[:12]
        candidate = base
        suffix = 2
        while candidate in taken:
            candidate = f"{base}{suffix}"
            suffix += 1
            if suffix > 999:
                raise SystemExit(f"не подобрать ключ для {hint}")
        taken.add(candidate)
        return candidate

    async def ensure_structure(self, db: AsyncSession, spec: dict) -> ProjectCtx:
        project_id = self._id(KIND_PROJECT, spec["weeek_id"])
        ctx = ProjectCtx(project_id=project_id, stage_ids={})

        for stage in spec["stages"]:
            stage_id = self._id(KIND_STAGE, f"{spec['weeek_id']}/{stage['key']}")
            ctx.stage_ids[stage["key"]] = stage_id
            if await db.get(ProjectStage, stage_id) is None:
                db.add(
                    ProjectStage(
                        id=stage_id,
                        tenant_id=self.tenant_id,
                        project_id=project_id,
                        name=stage["name"][:255],
                        position=int(stage["position"]),
                    )
                )
                self.bump("этапов создано")


        for cfd in spec["custom_fields"]:
            field_id = self._id(KIND_CUSTOM_FIELD, f"{spec['weeek_id']}/{cfd['weeek_id']}")
            ctx.field_ids[cfd["weeek_id"]] = field_id
            if await db.get(CustomFieldDefinition, field_id) is None:
                db.add(
                    CustomFieldDefinition(
                        id=field_id,
                        tenant_id=self.tenant_id,
                        project_id=project_id,
                        name=cfd["name"][:64],
                        type=cfd["type"],
                        options=[
                            {k: v for k, v in o.items() if v is not None}
                            for o in cfd.get("options") or []
                        ],
                        position=int(cfd["position"]),
                    )
                )
                self.bump("кастом-полей создано")

        await db.flush()
        # UNIQUE(project_id, position) у этапов и секций — DEFERRABLE: без
        # явной проверки дубль позиции выстрелил бы на COMMIT, уронив пачку
        # задач и не показав виновника.
        await db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        return ctx

    # ─── задачи ─────────────────────────────────────────────────────────────

    async def import_tasks(self, db: AsyncSession, spec: dict, ctx: ProjectCtx) -> list[dict]:
        payload = json.loads((self.bundle / spec["tasks_file"]).read_text(encoding="utf-8"))
        rows: list[dict] = payload["tasks"]
        # Родители строго раньше детей: FK `parent_task_id` не отложенный, а
        # ребёнок из первого чанка не нашёл бы родителя из второго.
        rows.sort(key=lambda r: r.get("parent_weeek_id") is not None)
        for start in range(0, len(rows), CHUNK):
            await self._import_chunk(db, spec, ctx, rows[start : start + CHUNK])
            await self._finish(db)
        return rows

    async def _import_chunk(
        self, db: AsyncSession, spec: dict, ctx: ProjectCtx, chunk: list[dict]
    ) -> None:
        ids = {int(r["weeek_id"]): self._id(KIND_TASK, r["weeek_id"]) for r in chunk}
        found = await db.execute(select(Task.id).where(Task.id.in_(list(ids.values()))))
        existing = {t for (t,) in found.all()}
        fresh = [r for r in chunk if ids[int(r["weeek_id"])] not in existing]
        self.bump("задач уже было", len(chunk) - len(fresh))
        if not fresh:
            return

        tasks: list[dict[str, Any]] = []
        assignees: list[dict[str, Any]] = []
        watchers: list[dict[str, Any]] = []
        values: list[dict[str, Any]] = []
        activity: list[dict[str, Any]] = []

        for row in fresh:
            task_id = ids[int(row["weeek_id"])]
            resolved: list[UUID] = []
            missing: list[str] = []
            for person in row.get("assignees") or []:
                employee_id = self.people.get((person.get("email") or "").lower())
                if employee_id is None:
                    missing.append(person.get("name") or person.get("email") or "")
                elif employee_id not in resolved:
                    resolved.append(employee_id)
            parent_note, attach_note = notes_for(row, self.tenant_id)
            description = compose_description(
                row.get("body_md"),
                weeek_id=int(row["weeek_id"]),
                parent_note=parent_note,
                attachments_note=attach_note,
                assignee_note_text=assignee_note(missing),
            )
            author = self.people.get((row.get("author_email") or "").lower(), self.actor_id)
            created_at = _instant(row.get("created_at")) or datetime.now(UTC)
            done = bool(row["done"])
            parent_weeek = row.get("parent_weeek_id")
            tasks.append(
                {
                    "id": task_id,
                    "tenant_id": self.tenant_id,
                    "project_id": ctx.project_id,
                    "parent_task_id": (
                        self._id(KIND_TASK, parent_weeek) if parent_weeek else None
                    ),
                    # Без статуса — не на доске (0046).
                    "stage_id": (
                        ctx.stage_ids[row["stage_key"]] if row["stage_key"] else None
                    ),
                    "title": row["title"],
                    "description": description,
                    # done и completed_at пишутся ПАРОЙ в одной вставке: CHECK
                    # ck_tasks_done_completed_at сторожит согласованность пары,
                    # а не путь записи. Через set_done дата стала бы «сегодня».
                    "done": done,
                    "completed_at": _instant(row.get("completed_at")) if done else None,
                    "priority": row["priority"],
                    "created_by": author,
                    "start_at": _noon(row.get("start_day"), row.get("due_day")),
                    "due_at": _noon(row.get("due_day"), None),
                    "position": row["position"],
                    "seq": row["seq"],
                    # Явно, поверх server_default: без этого архив 2022 года
                    # выглядел бы созданным сегодня. `updated_at` тоже явно —
                    # у колонки onupdate=now(), а поиск сортирует по ней.
                    "created_at": created_at,
                    "updated_at": _instant(row.get("updated_at")) or created_at,
                }
            )
            for position, employee_id in enumerate(resolved):
                assignees.append(
                    {
                        "task_id": task_id,
                        "employee_id": employee_id,
                        "tenant_id": self.tenant_id,
                        "position": position,
                        "assigned_by": self.actor_id,
                        "assigned_at": created_at,
                    }
                )
                # Наблюдатель только у ОТКРЫТОЙ задачи: у выполненной он давал
                # бы лишь шум «прокомментировали / вернули в работу».
                if not done:
                    watchers.append(
                        {
                            "task_id": task_id,
                            "employee_id": employee_id,
                            "tenant_id": self.tenant_id,
                            "added_reason": "assignee",
                            "added_at": created_at,
                        }
                    )
            for value in row.get("custom_values") or []:
                field_id = ctx.field_ids.get(value["field"])
                if field_id is not None:
                    values.append(
                        {
                            "task_id": task_id,
                            "field_id": field_id,
                            "tenant_id": self.tenant_id,
                            "value": value["value"],
                        }
                    )
            activity.append(
                {
                    "tenant_id": self.tenant_id,
                    "task_id": task_id,
                    "actor_id": author,
                    "kind": "created",
                    "payload": {"title": row["title"], "source": "weeek",
                                "weeek_id": row["weeek_id"]},
                    "created_at": created_at,
                }
            )

        await db.execute(insert(Task), tasks)
        if assignees:
            await db.execute(insert(TaskAssignee), assignees)
        if watchers:
            await db.execute(insert(TaskWatcher), watchers)
        if values:
            await db.execute(insert(TaskCustomFieldValue), values)
        await record_activities(db, activity)
        self.bump("задач создано", len(tasks))
        self.bump("исполнителей проставлено", len(assignees))

    # ─── участники ──────────────────────────────────────────────────────────

    async def ensure_members(self, db: AsyncSession, spec: dict, ctx: ProjectCtx) -> None:
        rows = await db.execute(
            select(ProjectMember.employee_id).where(ProjectMember.project_id == ctx.project_id)
        )
        present = {e for (e,) in rows.all()}
        for email in spec.get("team_emails") or []:
            employee_id = self.people.get(email.lower())
            if employee_id is None or employee_id in present:
                continue
            db.add(
                ProjectMember(
                    tenant_id=self.tenant_id,
                    project_id=ctx.project_id,
                    employee_id=employee_id,
                    role=TEAM_ROLE,
                    added_by=self.actor_id,
                )
            )
            present.add(employee_id)
            self.bump("участников добавлено")
        await db.flush()

    # ─── вложения ───────────────────────────────────────────────────────────

    def _attachment_id(self, row: dict, att: dict) -> UUID:
        return self._id(KIND_ATTACHMENT, f"{row['weeek_id']}/{att['weeek_id']}")

    async def import_attachments(self, db: AsyncSession, rows: list[dict]) -> None:
        pending = [(r, a) for r in rows for a in (r.get("attachments") or [])]
        if not pending:
            return
        # Ключ — ПАРА (задача, файл): один и тот же файл WEEEK бывает
        # приложен к двум задачам, и общий id ронял бы task_attachments_pkey.
        ids = [self._attachment_id(r, a) for r, a in pending]
        found = await db.execute(select(TaskAttachment.id).where(TaskAttachment.id.in_(ids)))
        existing = {i for (i,) in found.all()}
        for row, att in pending:
            attachment_id = self._attachment_id(row, att)
            if attachment_id in existing:
                self.bump("вложений уже было")
                continue
            source = self.bundle / att["file"]
            if not source.is_file():
                log.warning("weeek.attachment_missing", file=att["file"])
                self.bump("вложений нет в бандле")
                continue
            mime = resolve_mime(att.get("mime"), att["name"])
            head = source.open("rb").read(SNIFF_HEAD_BYTES)
            if mime not in ALLOWED_MIME or sniff_mismatch(mime, head):
                # Тот же fail-closed, что в ручке загрузки: белый список —
                # защитный инвариант, ради переноса его не расширяем.
                log.warning("weeek.attachment_rejected", name=att["name"], mime=mime)
                self.bump("вложений отклонено")
                continue
            task_id = self._id(KIND_TASK, row["weeek_id"])
            key, _sanitized = storage_key_for(
                self.tenant_id, task_id, att["name"], unique=str(att["weeek_id"])
            )
            target = absolute_path(key)
            if self.apply and not target.exists():
                # Каталог создаём тоже только при записи: разбор не должен
                # оставлять на диске ни файла, ни пустой папки.
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
            db.add(
                TaskAttachment(
                    id=attachment_id,
                    tenant_id=self.tenant_id,
                    task_id=task_id,
                    uploaded_by=self.people.get(
                        (att.get("creator_email") or "").lower(), self.actor_id
                    ),
                    # Имя в базе — ОРИГИНАЛЬНОЕ: `_sanitize_filename` оставляет
                    # от «отчёт.pdf» только «pdf». Санитизированное живёт
                    # внутри storage_key, то есть в пути на диске.
                    filename=att["name"][:255],
                    mime=mime,
                    size_bytes=int(att["size"]),
                    storage_key=key,
                )
            )
            self.bump("вложений перенесено")
        await db.flush()

    # ─── прогон ─────────────────────────────────────────────────────────────

    async def run(self, db: AsyncSession) -> None:
        manifest = json.loads((self.bundle / "manifest.json").read_text(encoding="utf-8"))
        _validate(manifest, self.bundle)
        await self.assert_tenant_scope(db)
        await self.load_people(db)
        folder_ids = await self.ensure_folders(db, manifest["folders"])
        await self._finish(db)
        taken = await self.taken_keys(db)

        for spec in manifest["projects"]:
            try:
                _project, _created = await self.ensure_project(db, spec, folder_ids, taken)
                ctx = await self.ensure_structure(db, spec)
                await self._finish(db)
                rows = await self.import_tasks(db, spec, ctx)
                await self.ensure_members(db, spec, ctx)
                await self._finish(db)
                await self.import_attachments(db, rows)
                await self._finish(db)
            except Exception:
                await db.rollback()
                log.exception("weeek.project_failed", project=spec["name"])
                self.bump("проектов с ошибкой")
            else:
                log.info("weeek.project_done", project=spec["name"], tasks=spec["task_count"])

        if not self.apply:
            await db.rollback()


def _instant(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _noon(day: str | None, not_after: str | None) -> datetime | None:
    """День → полдень display tz, единственный допустимый способ.

    `not_after` отбрасывает старт позже срока: на Тайм-лайне и в календаре
    такая пара рисует полосу отрицательной длины.
    """
    if not day:
        return None
    if not_after and day > not_after:
        return None
    try:
        return due_noon_utc(date.fromisoformat(day))
    except ValueError:
        return None


def _validate(manifest: dict, bundle: Path) -> None:
    """Проверить bundle ДО первой вставки: 422 внутри пачки уронил бы чанк."""
    for spec in manifest["projects"]:
        for cfd in spec.get("custom_fields") or []:
            for option in cfd.get("options") or []:
                # `CustomFieldOption.id` — max_length=32. В JSONB ограничения
                # нет, поэтому длинный id записался бы молча, а список полей
                # проекта после этого отдавал бы 500 (staging, 25.08).
                if len(str(option.get("id", ""))) > 32:
                    raise SystemExit(
                        f"поле «{cfd['name']}»: id опции длиннее 32 символов — "
                        f"{option['id']!r}"
                    )
        path = bundle / spec["tasks_file"]
        if not path.is_file():
            raise SystemExit(f"нет файла задач: {spec['tasks_file']}")
        stage_keys = {s["key"] for s in spec["stages"]}
        rows = json.loads(path.read_text(encoding="utf-8"))["tasks"]
        for row in rows:
            # `stage_key: null` — задача без статуса (0046), это норма.
            if row["stage_key"] is not None and row["stage_key"] not in stage_keys:
                raise SystemExit(f"задача {row['weeek_id']}: этап {row['stage_key']!r} не объявлен")
            if row["done"] and not row.get("completed_at"):
                raise SystemExit(f"задача {row['weeek_id']}: done без даты закрытия")


async def resolve_tenant_and_actor(slug: str, actor_email: str) -> tuple[UUID, UUID]:
    async with tenant_scoped_session(None, bypass_rls=True) as scan:
        tenant_id = (
            await scan.execute(select(ShadowTenant.id).where(ShadowTenant.slug == slug))
        ).scalar_one_or_none()
        if tenant_id is None:
            raise SystemExit(f"тенант {slug!r} не найден")
        actor_id = (
            await scan.execute(
                select(ShadowUser.employee_id).where(
                    func.lower(ShadowUser.email) == actor_email.lower(),
                    ShadowUser.tenant_id == tenant_id,
                    ShadowUser.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if actor_id is None:
            raise SystemExit(f"{actor_email} не заходил в Hub — актора нет")
        return tenant_id, actor_id


def _principal(actor_id: UUID, tenant_id: UUID, email: str) -> Principal:
    return Principal(
        employee_id=actor_id,
        email=email,
        tenant_id=tenant_id,
        tenant_slug="",
        full_name="",
        product_roles={"hub": "admin"},
        jti=str(uuid.uuid4()),
    )


async def main() -> int:
    log_config.configure()
    parser = argparse.ArgumentParser(description="Перенос задач из WEEEK в Hub")
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--tenant-slug", default="uppetit")
    parser.add_argument("--actor-email", required=True)
    parser.add_argument("--apply", action="store_true", help="записать (по умолчанию разбор)")
    args = parser.parse_args()

    tenant_id, actor_id = await resolve_tenant_and_actor(args.tenant_slug, args.actor_email)
    importer = Importer(args.bundle, tenant_id=tenant_id, actor_id=actor_id, apply=args.apply)
    async with tenant_scoped_session(tenant_id) as db:
        await importer.run(db)

    log.info("weeek.summary", applied=args.apply, **dict(importer.stats))
    if not args.apply:
        log.info("weeek.dry_run", hint="повторите с --apply, чтобы записать")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

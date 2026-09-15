"""One-shot: перенести живые задачи из чужого личного в личное исполнителя.

Решение владельца 15.09: «если задачу назначили лично мне — я должен видеть её
в СВОЁМ личном проекте, а не в её, ибо я исполнитель». На живом пути правило
держит `services/personal_handoff.py` (зовётся из каждой ручки, меняющей состав
исполнителей), но строки, заведённые ДО выката, лежат по-старому — их и
переносит этот прогон.

**Переносим не всё.** Условия ровно те, при которых перенос однозначен:

- задача не выполнена и не в архиве — история остаётся историей, переносить
  закрытое значит переписывать прошлое;
- исполнитель РОВНО один и он не владелец личного — двоих в личное не
  положить, а «положить к одному из» было бы угадыванием;
- задача не подзадача — семья переезжает целиком, в одиночку нельзя;
- автор задачи = владелец личного проекта — тогда актором переноса законно
  выступает он: `assert_movable` требует, чтобы источник был СВОИМ личным, а
  `_plan_watchers` не отписывает того, кто переносит;
- у исполнителя уже есть личное пространство (оно заводится первым входом).

Всё, что не подошло, попадает в отчёт поимённо и не трогается — таких строк
единицы, и разобраться с ними руками дешевле, чем кодировать догадки.

Замер на проде 15.09: под перенос подходят 2 задачи (LICNOE20-2, LICNOE26-5),
ещё 2 выполненные остаются на месте.

    .venv/bin/python -m app.jobs.handoff_personal_tasks            # разбор
    .venv/bin/python -m app.jobs.handoff_personal_tasks --apply    # запись
"""

from __future__ import annotations

import argparse
import asyncio
import uuid
from dataclasses import dataclass, field
from uuid import UUID

import structlog
from fastapi import HTTPException
from signaris_auth import Principal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import log as log_config
from app.db import tenant_scoped_session
from app.models.project import Project
from app.models.shadow import ShadowUser
from app.models.task import Task, TaskAssignee
from app.services.personal_projects import get_personal_project_id
from app.services.project_access import ensure_project_member
from app.services.task_move import apply_move, plan_move
from app.services.task_watchers import ensure_watcher

log = structlog.get_logger("jobs.handoff_personal_tasks")


@dataclass
class Report:
    """Что переедет (или переехало) и что осталось лежать — с причинами."""

    moved: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)


def _actor(user: ShadowUser, tenant_id: UUID) -> Principal:
    """Principal владельца личного проекта — от его имени и переносим.

    Системного актора в Hub нет (`tasks.created_by` — FK на `shadow_users`), да
    он бы и не подошёл: перенос из личного разрешён только его владельцу.
    """
    return Principal(
        employee_id=user.employee_id,
        email=user.email or "",
        tenant_id=tenant_id,
        tenant_slug="",
        full_name=user.full_name or "",
        product_roles={"hub": "member"},
        jti=str(uuid.uuid4()),
    )


async def _tenant_ids() -> list[UUID]:
    async with tenant_scoped_session(None, bypass_rls=True) as scan:
        rows = await scan.execute(
            select(Project.tenant_id)
            .where(Project.personal_owner_id.is_not(None))
            .distinct()
        )
        return [r[0] for r in rows]


async def handoff_tenant(  # noqa: C901 — линейный разбор случаев, дробить нечего
    session: AsyncSession, tenant_id: UUID, *, apply: bool
) -> Report:
    """Разобрать один тенант; при `apply` — записать. Commit за вызывающим."""
    report = Report()
    personal = {
        p.id: p
        for p in (
            await session.execute(
                select(Project).where(Project.personal_owner_id.is_not(None))
            )
        )
        .scalars()
        .all()
    }
    if not personal:
        return report

    tasks = list(
        (
            await session.execute(
                select(Task)
                .where(
                    Task.project_id.in_(personal),
                    Task.done.is_(False),
                    Task.archived_at.is_(None),
                )
                .order_by(Task.project_id, Task.seq)
            )
        )
        .scalars()
        .all()
    )
    for task in tasks:
        source = personal[task.project_id]
        owner_id = source.personal_owner_id
        if owner_id is None:  # pragma: no cover — выборка была по personal
            continue
        assignees = list(
            (
                await session.execute(
                    select(TaskAssignee.employee_id).where(
                        TaskAssignee.task_id == task.id
                    )
                )
            )
            .scalars()
            .all()
        )
        if not assignees or assignees == [owner_id]:
            continue  # обычная личная задача — она уже на месте
        label = f"{source.key}-{task.seq} «{task.title}»"
        if len(assignees) > 1:
            report.skipped.append((label, "исполнителей больше одного"))
            continue
        if task.parent_task_id is not None:
            report.skipped.append((label, "подзадача — едет только с родителем"))
            continue
        if task.created_by != owner_id:
            report.skipped.append((label, "автор не владелец личного"))
            continue
        target_id = await get_personal_project_id(session, assignees[0])
        if target_id is None:
            report.skipped.append((label, "у исполнителя нет личного пространства"))
            continue
        target = await session.get(Project, target_id)
        owner = await session.get(ShadowUser, owner_id)
        if target is None or owner is None:  # pragma: no cover
            report.skipped.append((label, "нет проекта-цели или владельца"))
            continue
        principal = _actor(owner, tenant_id)
        try:
            plan = await plan_move(
                session,
                task=task,
                source=source,
                target=target,
                principal=principal,
                handoff=True,
            )
        except HTTPException as err:
            report.skipped.append((label, str(err.detail)))
            continue
        report.moved.append(f"{label} → {target.key}")
        if not apply:
            continue
        await apply_move(session, plan=plan, principal=principal)
        # Автор остаётся при своей задаче ЯВНО — тем же шагом, что на живом
        # пути: подписка даёт ему `personal_task_scope`, членство — карточку
        # (без него `get_task` ответил бы 404, а перенос раздаёт членство
        # только исполнителям).
        await ensure_watcher(
            session,
            task_id=task.id,
            tenant_id=tenant_id,
            employee_id=owner_id,
            reason="creator",
        )
        await ensure_project_member(
            session,
            project_id=target.id,
            tenant_id=tenant_id,
            employee_id=owner_id,
            added_by=owner_id,
        )
    return report


async def main() -> int:
    log_config.configure()
    parser = argparse.ArgumentParser(description="Задачи — в личное исполнителя")
    parser.add_argument(
        "--apply", action="store_true", help="записать (по умолчанию только разбор)"
    )
    args = parser.parse_args()

    total = Report()
    for tenant_id in await _tenant_ids():
        async with tenant_scoped_session(tenant_id) as session:
            report = await handoff_tenant(session, tenant_id, apply=args.apply)
            if args.apply:
                await session.commit()
        total.moved.extend(report.moved)
        total.skipped.extend(report.skipped)

    # Отчёт — через structlog, как остальные джобы: одинаково читается и в
    # терминале, и в journalctl.
    log.info(
        "handoff.summary",
        applied=args.apply,
        to_move=len(total.moved),
        skipped=len(total.skipped),
    )
    for label in total.moved:
        log.info("handoff.moved" if args.apply else "handoff.pending", task=label)
    for label, why in total.skipped:
        log.info("handoff.skipped", task=label, reason=why)
    if not args.apply:
        log.info("handoff.dry_run", hint="повторите с --apply, чтобы записать")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

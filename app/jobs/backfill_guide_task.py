"""One-shot: раздать задачу-инструкцию тем, у кого личный проект уже был.

На живом пути задача заводится в момент создания личного проекта
(`onboarding.create_guide_task` в `ensure_personal_project`) — по построению
один раз на сотрудника. Но к моменту выката личное пространство уже есть у
всех нынешних (0042, 24.08), и «первый вход» для них позади: без этого прогона
инструкцию увидели бы только будущие сотрудники.

Идемпотентность — по заголовку задачи в личном проекте. Этого достаточно
одноразовому `--apply`, но означает: сотрудник, удаливший задачу ДО повторного
запуска, получит её снова. Поэтому прогонять ОДИН раз.

    .venv/bin/python -m app.jobs.backfill_guide_task            # разбор
    .venv/bin/python -m app.jobs.backfill_guide_task --apply    # запись
"""

from __future__ import annotations

import argparse
import asyncio
import uuid
from uuid import UUID

import structlog
from signaris_auth import Principal
from sqlalchemy import select

from app import log as log_config
from app.db import tenant_scoped_session
from app.models.project import Project
from app.models.shadow import ShadowUser
from app.services.onboarding import create_guide_task, has_guide_task

log = structlog.get_logger("jobs.backfill_guide_task")


def _owner_principal(user: ShadowUser, tenant_id: UUID) -> Principal:
    """Principal владельца личного проекта — от его имени и заводим задачу.

    Системного актора в Hub нет: `tasks.created_by` — FK на `shadow_users`, и
    подставить «сервер» некуда. Автор = сам сотрудник, ровно как на живом пути.
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
            select(Project.tenant_id).where(Project.personal_owner_id.is_not(None)).distinct()
        )
        return [r[0] for r in rows]


async def main() -> int:
    log_config.configure()
    parser = argparse.ArgumentParser(description="Задача-инструкция нынешним сотрудникам")
    parser.add_argument(
        "--apply", action="store_true", help="записать (по умолчанию только разбор)"
    )
    args = parser.parse_args()

    created: list[str] = []
    skipped: list[str] = []
    orphans: list[str] = []

    for tenant_id in await _tenant_ids():
        async with tenant_scoped_session(tenant_id) as session:
            projects = list(
                (
                    await session.execute(
                        select(Project).where(Project.personal_owner_id.is_not(None))
                    )
                )
                .scalars()
                .all()
            )
            for project in projects:
                owner = await session.get(ShadowUser, project.personal_owner_id)
                if owner is None or owner.deleted_at is not None:
                    # Уволенный: личный проект остаётся историей, будить его
                    # задачей незачем.
                    orphans.append(str(project.personal_owner_id))
                    continue
                label = owner.full_name or owner.email or str(owner.employee_id)
                if await has_guide_task(session, project.id):
                    skipped.append(label)
                    continue
                created.append(label)
                if args.apply:
                    task = await create_guide_task(
                        session,
                        principal=_owner_principal(owner, tenant_id),
                        project_id=project.id,
                    )
                    if task is None:
                        log.warning("backfill.guide_task_failed", owner=label)
            if args.apply:
                await session.commit()

    # Отчёт — через structlog, как остальные джобы: вывод одинаково читается
    # и в терминале, и в journalctl.
    log.info(
        "backfill.guide_task.summary",
        applied=args.apply,
        already_had=len(skipped),
        to_create=len(created),
        skipped_deleted_owners=len(orphans),
    )
    for label in created:
        log.info("guide_task.created" if args.apply else "guide_task.pending", owner=label)
    if not args.apply:
        log.info("backfill.dry_run", hint="повторите с --apply, чтобы записать")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

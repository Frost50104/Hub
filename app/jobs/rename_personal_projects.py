"""One-shot: «Личное»/LICNOE26 → «Мои задачи»/PETRPOPOV у существующих проектов.

Смена констант в `services/personal_projects.py` действует только на НОВЫХ
сотрудников — у тех, кто уже заходил, проект создан и переименовываться сам не
будет. На проде это 178 проектов, все названные «Личное».

**Что переименовываем.** Только точное имя `"Личное"`: `PATCH /projects/{id}`
личному проекту не запрещён (`assert_not_personal` стоит на папке, архиве и
удалении, но не на переименовании), значит осознанно выбранное имя существует
в принципе, и затирать его нельзя. Всё остальное — в отчёт.

**Что перевыдаём.** Ключ, если он ещё не в целевом виде. Идемпотентность — по
регулярке `^{base}\\d*$`: повторный `--apply` ничего не делает.

**Чего НЕ трогаем.** `tasks.seq` и `projects.next_task_seq`: нумерация задач от
ключа не зависит, меняется только печатаемый префикс. Ссылок вида «LICNOE…» в
комментариях, уведомлениях и аудите на проде ноль; две записи в ленте переноса
останутся историческим снимком — так и задумано.

    .venv/bin/python -m app.jobs.rename_personal_projects            # разбор
    .venv/bin/python -m app.jobs.rename_personal_projects --apply    # запись
    .venv/bin/python -m app.jobs.rename_personal_projects \\
        --employee <uuid> --key POPOVP --apply   # ручная правка одного ключа

Последняя форма — единственный способ поправить ключ вообще: в `ProjectUpdate`
поля `key` нет, а собрать из `full_name` именно фамилию нельзя (порядок слов в
справочнике смешанный). Поэтому приёмка — чтение dry-run-отчёта глазами.
"""

from __future__ import annotations

import argparse
import asyncio
import re
from dataclasses import dataclass, field
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import log as log_config
from app.db import tenant_scoped_session
from app.models.project import Project
from app.models.shadow import ShadowUser
from app.services import audit
from app.services.personal_projects import (
    PERSONAL_KEY_MAX_LEN,
    PERSONAL_PROJECT_NAME,
    personal_key_base,
)

log = structlog.get_logger("jobs.rename_personal_projects")

OLD_NAME = "Личное"
_MAX_SUFFIX = 1000


@dataclass
class Report:
    renamed: list[str] = field(default_factory=list)
    rekeyed: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)


async def _tenant_ids() -> list[UUID]:
    async with tenant_scoped_session(None, bypass_rls=True) as scan:
        rows = await scan.execute(
            select(Project.tenant_id)
            .where(Project.personal_owner_id.is_not(None))
            .distinct()
        )
        return [r[0] for r in rows]


def _free_key(base: str, used: set[str]) -> str | None:
    if base not in used:
        return base
    for i in range(2, _MAX_SUFFIX):
        candidate = f"{base}{i}"
        if candidate not in used:
            return candidate
    return None


async def rename_tenant(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    apply: bool,
    only_employee: UUID | None = None,
    forced_key: str | None = None,
) -> Report:
    """Разобрать один тенант; при `apply` — записать. Commit за вызывающим."""
    report = Report()
    # Порядок детерминированный: после падения посреди прогона повтор раздаст
    # тёзкам те же `POPOV`/`POPOV2`, а не перемешает их.
    projects = list(
        (
            await session.execute(
                select(Project)
                .where(Project.personal_owner_id.is_not(None))
                .order_by(Project.created_at, Project.id)
            )
        )
        .scalars()
        .all()
    )
    if not projects:
        return report

    # Занятые ключи — ВСЕ проекты тенанта, не только личные: namespace общий
    # (`UNIQUE(tenant_id, key)`), и рабочий «POPOV» уводит личный в «POPOV2».
    used = set(
        (await session.execute(select(Project.key))).scalars().all()
    )

    for project in projects:
        owner = await session.get(ShadowUser, project.personal_owner_id)
        label = f"{project.key} · {owner.full_name if owner else '—'}"
        if only_employee is not None and project.personal_owner_id != only_employee:
            continue

        new_name = PERSONAL_PROJECT_NAME if project.name == OLD_NAME else None
        if project.name != OLD_NAME and project.name != PERSONAL_PROJECT_NAME:
            report.skipped.append((label, f"имя выбрано человеком: «{project.name}»"))

        base = forced_key or personal_key_base(owner.full_name if owner else None)
        if len(base) > PERSONAL_KEY_MAX_LEN:
            report.skipped.append((label, f"ключ длиннее {PERSONAL_KEY_MAX_LEN}"))
            base = ""
        new_key = None
        if base:
            if forced_key:
                new_key = base if base not in used else None
                if new_key is None:
                    report.skipped.append((label, f"ключ {base} занят"))
            elif re.fullmatch(rf"{re.escape(base)}\d*", project.key):
                pass  # уже в целевом виде — повторный прогон
            else:
                new_key = _free_key(base, used)
                if new_key is None:
                    report.skipped.append((label, "свободный суффикс не найден"))

        if new_name is None and new_key is None:
            continue
        if new_key:
            report.rekeyed.append(f"{project.key} → {new_key} ({label})")
        if new_name:
            report.renamed.append(label)
        if not apply:
            if new_key:
                used.add(new_key)
            continue

        diff: dict[str, dict[str, str]] = {}
        old_key, old_name = project.key, project.name
        if new_key:
            project.key = new_key
            used.add(new_key)
            diff["key"] = {"old": old_key, "new": new_key}
        if new_name:
            project.name = new_name
            diff["name"] = {"old": old_name, "new": new_name}
        # actor_id=None — «инициатор не человек», как у переименований из фида
        # auth. Массовая правка user-visible ключей без следа в журнале — ровно
        # то, от чего аудит и существует.
        audit.record(
            session,
            tenant_id=tenant_id,
            actor_id=None,
            action="update",
            object_type="project",
            object_id=project.id,
            object_label=f"{old_key} · {old_name}",
            diff=diff,
        )
        try:
            # Флашим КАЖДЫЙ проект: параллельный `GET /api/me` мог завести
            # личный проект новому сотруднику и занять наш ключ между сканом и
            # UPDATE, а IntegrityError в общей транзакции убил бы весь тенант.
            await session.flush()
        except IntegrityError:
            await session.rollback()
            report.skipped.append((label, "ключ занят конкурентом, нужен повтор"))
            return report

    return report


async def main() -> int:
    log_config.configure()
    parser = argparse.ArgumentParser(description="Личное → «Мои задачи» + ключ из ФИО")
    parser.add_argument("--apply", action="store_true", help="записать")
    parser.add_argument("--employee", help="UUID сотрудника — править только его")
    parser.add_argument("--key", help="задать ключ вручную (с --employee)")
    args = parser.parse_args()
    if args.key and not args.employee:
        parser.error("--key задаётся только вместе с --employee")

    total = Report()
    for tenant_id in await _tenant_ids():
        async with tenant_scoped_session(tenant_id) as session:
            report = await rename_tenant(
                session,
                tenant_id,
                apply=args.apply,
                only_employee=UUID(args.employee) if args.employee else None,
                forced_key=args.key,
            )
            if args.apply:
                await session.commit()
        total.renamed.extend(report.renamed)
        total.rekeyed.extend(report.rekeyed)
        total.skipped.extend(report.skipped)

    log.info(
        "rename.summary",
        applied=args.apply,
        renamed=len(total.renamed),
        rekeyed=len(total.rekeyed),
        skipped=len(total.skipped),
    )
    for line in total.rekeyed:
        log.info("rename.key" if args.apply else "rename.key_pending", project=line)
    for label, why in total.skipped:
        log.info("rename.skipped", project=label, reason=why)
    if not args.apply:
        log.info("rename.dry_run", hint="повторите с --apply, чтобы записать")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

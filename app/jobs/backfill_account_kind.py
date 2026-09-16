"""One-shot: разметить карточки касс, до которых синк не дотянется.

Основную работу делает сам staff-sync: с 0056 он пишет `account_kind` в тень и
сверяет вид у карточки ДАЖЕ в ветке `already_linked` — до этой правки 54
карточки-кассы из 55 на проде возвращали `already_linked` до любой записи и
признак не получили бы никогда.

Остаётся хвост, который синк починить не может **по построению**: карточка, у
которой тени нет вовсе. На проде такая одна — «Кондратьевский, 18»
(`k18@uppetit.ru`): auth про эту учётку не знает, в фиде её нет, сопоставлять
не с чем. Прятать её «по имени» нельзя — регулярка по полю, которое правит
человек, уже даёт ложное срабатывание («Аккаунт Тесты 2»). Поэтому такие
карточки размечаются ЯВНЫМ списком, с записью в аудит.

    .venv/bin/python -m app.jobs.backfill_account_kind                  # разбор
    .venv/bin/python -m app.jobs.backfill_account_kind --apply          # по теням
    .venv/bin/python -m app.jobs.backfill_account_kind \\
        --service <profile-uuid> --service <profile-uuid> --apply       # сироты

Идемпотентна: повторный `--apply` не находит расхождений и ничего не пишет.
"""

from __future__ import annotations

import argparse
import asyncio
from uuid import UUID

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import bypass_session_factory
from app.models.audit import AuditLog
from app.models.employee_profile import EmployeeProfile
from app.models.shadow import ShadowUser

log = structlog.get_logger("jobs.backfill_account_kind")


async def _plan(db: AsyncSession) -> tuple[list[EmployeeProfile], list[EmployeeProfile]]:
    """→ (карточки с тенью-service и неверным видом, кассы без тени вовсе)."""
    by_shadow = (
        (
            await db.execute(
                select(EmployeeProfile)
                .join(ShadowUser, ShadowUser.employee_id == EmployeeProfile.employee_id)
                .where(
                    ShadowUser.account_kind == "service",
                    EmployeeProfile.account_kind != "service",
                )
            )
        )
        .scalars()
        .all()
    )
    # Карточки без тени: синк их не видит, поэтому вид может быть только
    # проставлен руками. Возвращаем для отчёта — решает человек.
    orphans = (
        (
            await db.execute(
                select(EmployeeProfile).where(
                    EmployeeProfile.status == "active",
                    EmployeeProfile.employee_id.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    return list(by_shadow), list(orphans)


async def _mark(db: AsyncSession, profiles: list[EmployeeProfile], reason: str) -> None:
    for p in profiles:
        db.add(
            AuditLog(
                tenant_id=p.tenant_id,
                actor_id=None,
                action="update",
                object_type="employee_profile",
                object_id=p.id,
                object_label=p.full_name,
                diff={
                    "account_kind": {"old": p.account_kind, "new": "service"},
                    "job": "backfill_account_kind",
                    "reason": reason,
                },
            )
        )
    await db.execute(
        update(EmployeeProfile)
        .where(EmployeeProfile.id.in_([p.id for p in profiles]))
        .values(account_kind="service")
    )


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="записать (иначе разбор)")
    parser.add_argument(
        "--service",
        action="append",
        default=[],
        help="id карточки-кассы без тени; можно повторять",
    )
    args = parser.parse_args()
    explicit = {UUID(v) for v in args.service}

    async with bypass_session_factory()() as db:
        by_shadow, orphans = await _plan(db)

        log.info("backfill.by_shadow", count=len(by_shadow))
        for p in by_shadow:
            log.info("backfill.by_shadow.row", name=p.full_name, email=p.email)
        log.info("backfill.orphans", count=len(orphans), hint="вид решает человек")
        for p in orphans:
            log.info(
                "backfill.orphan",
                profile_id=str(p.id),
                name=p.full_name,
                email=p.email,
                chosen=p.id in explicit,
            )

        chosen = [p for p in orphans if p.id in explicit]
        missing = explicit - {p.id for p in chosen}
        if missing:
            raise SystemExit(f"Не найдены среди карточек без тени: {sorted(map(str, missing))}")

        if not args.apply:
            log.info("backfill.dry_run", hint="повторите с --apply, чтобы записать")
            return

        if by_shadow:
            await _mark(db, by_shadow, "shadow_account_kind")
        if chosen:
            await _mark(db, chosen, "explicit_no_shadow")
        await db.commit()
        log.info("backfill.done", marked=len(by_shadow) + len(chosen))


if __name__ == "__main__":
    asyncio.run(main())

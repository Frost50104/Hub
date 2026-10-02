"""Разовая кампания: напомнить людям точек-участниц гонки включить push.

Пуш «заезд стартовал» 02.10 получили во «Входящие» 152 человека, а на
устройства дошло 9 — подписок почти нет. Напоминание 18.09 слали удалённым
скриптом с прода (kind `race.push_reminder`, 134 строки, только «Входящие»);
в репозитории от него ничего не осталось — отсюда эта джоба.

Популяция — та же, что у `engine._recipients` («заезд стартовал»): активные
люди (не кассы) точек-участниц конкурса с привязанной учёткой. Минус те, у
кого есть живая подписка (`push_subscriptions.last_seen_at` свежее
`push_freshness_days`), минус уже получившие напоминание ЭТОЙ кампании
(`notifications.payload->>'campaign'`). Канал — только «Входящие»:
`queue_many` без `schedule_push_batch`, подписки у этих людей нет, пушить
некуда. Kind в `NOTIFICATION_KINDS` не добавляется (появился бы лишний
переключатель в настройках); Inbox и prefs терпят незнакомый вид — проверено
18.09.

Без `--apply` — только отчёт. Повторный `--apply` с той же `--campaign` не шлёт
ничего. Запуск на проде, как у остальных джоб:

    systemd-run --wait --pipe --uid=signaris \\
      -p EnvironmentFile=/opt/signaris-hub/.env -p WorkingDirectory=/opt/signaris-hub \\
      /opt/signaris-hub/.venv/bin/python -m app.jobs.race_push_reminder \\
      --tenant uppetit --campaign race-2026-10-05 [--contest <uuid>] [--apply]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter
from datetime import UTC, datetime, timedelta
from uuid import UUID

import structlog
from sqlalchemy import select

from app import log as log_config
from app.config import get_settings
from app.db import tenant_scoped_session
from app.models.employee_profile import EmployeeProfile
from app.models.notification import Notification
from app.models.push_subscription import PushSubscription
from app.models.race import RaceContest
from app.models.shadow import ShadowTenant
from app.services.audience_resolver import learning_population_filter
from app.services.notify_batch import queue_many
from app.services.race import read
from app.services.timefmt import fmt_day

log = structlog.get_logger("jobs.race_push_reminder")

KIND = "race.push_reminder"
TITLE = "Включите уведомления о гонке"
URL = "/settings/notifications"


def _say(text: str) -> None:
    sys.stdout.write(text + "\n")


def reminder_body(contest: RaceContest) -> str:
    when = "уже идёт" if contest.status == "active" else f"стартует {fmt_day(contest.starts_on)}"
    return (
        f"«{contest.title}» {when}. Чтобы получать старт заезда и рекорды своей точки "
        "на телефон, откройте Настройки → Уведомления и нажмите «Включить». "
        "На iPhone сначала добавьте Hub на экран «Домой» (Поделиться → На экран «Домой») "
        "и откройте оттуда."
    )


async def _tenant_id(slug: str) -> UUID | None:
    async with tenant_scoped_session(None, bypass_rls=True) as db:
        return (
            await db.execute(select(ShadowTenant.id).where(ShadowTenant.slug == slug))
        ).scalar_one_or_none()


async def main() -> int:
    log_config.configure()
    parser = argparse.ArgumentParser(description="Напоминание включить push людям точек гонки")
    parser.add_argument("--tenant", required=True, help="slug организации (например uppetit)")
    parser.add_argument(
        "--campaign", required=True, help="метка кампании для дедупа, например race-2026-10-05"
    )
    parser.add_argument(
        "--contest",
        help="id конкурса; по умолчанию — текущий (активный или ближайший запланированный)",
    )
    parser.add_argument(
        "--apply", action="store_true", help="записать во «Входящие» (по умолчанию только отчёт)"
    )
    args = parser.parse_args()

    tenant_id = await _tenant_id(args.tenant)
    if tenant_id is None:
        _say(f"организация «{args.tenant}» не найдена")
        return 2
    settings = get_settings()
    cutoff = datetime.now(UTC) - timedelta(days=settings.push_freshness_days)

    async with tenant_scoped_session(tenant_id) as session:
        contest = (
            await session.get(RaceContest, UUID(args.contest))
            if args.contest
            else await read.current_contest(session, tenant_id)
        )
        if contest is None:
            _say("конкурса нет: заведите или передайте --contest")
            return 3
        participants = await read.load_participants(session, contest)
        store_ids = [p.store_id for p in participants]
        store_names = {p.store_id: p.name for p in participants}
        population = (
            await session.execute(
                select(EmployeeProfile.employee_id, EmployeeProfile.store_id).where(
                    learning_population_filter(),
                    EmployeeProfile.store_id.in_(store_ids),
                )
            )
        ).all()
        no_login = sum(1 for emp, _ in population if emp is None)
        people = {emp: store for emp, store in population if emp is not None}
        ids = list(people)
        subscribed = (
            set(
                (
                    await session.execute(
                        select(PushSubscription.employee_id)
                        .where(
                            PushSubscription.employee_id.in_(ids),
                            PushSubscription.last_seen_at > cutoff,
                        )
                        .distinct()
                    )
                ).scalars()
            )
            if ids
            else set()
        )
        notified = (
            set(
                (
                    await session.execute(
                        select(Notification.employee_id)
                        .where(
                            Notification.employee_id.in_(ids),
                            Notification.kind == KIND,
                            Notification.payload["campaign"].astext == args.campaign,
                        )
                        .distinct()
                    )
                ).scalars()
            )
            if ids
            else set()
        )
        targets = [emp for emp in ids if emp not in subscribed and emp not in notified]

        _say(
            f"конкурс: «{contest.title}» · {contest.status} · {contest.starts_on} — {contest.ends_on}"
        )
        _say(f"точек-участниц: {len(store_ids)}")
        _say(f"людей в популяции: {len(people)} (+{no_login} без входа в Hub — недостижимы)")
        _say(f"с живой подпиской (≤ {settings.push_freshness_days} дн.): {len(subscribed)}")
        _say(f"уже получили напоминание «{args.campaign}»: {len(notified)}")
        _say(f"получат сейчас: {len(targets)}")
        by_store = Counter(store_names.get(people[emp], "?") for emp in targets)
        for name, n in sorted(by_store.items(), key=lambda kv: (-kv[1], kv[0])):
            _say(f"  {n:3d}  {name}")
        log.info(
            "race_push_reminder.plan",
            tenant=args.tenant,
            campaign=args.campaign,
            contest_id=str(contest.id),
            population=len(people),
            no_login=no_login,
            subscribed=len(subscribed),
            notified=len(notified),
            targets=len(targets),
            apply=args.apply,
        )
        if not args.apply:
            _say("разбор; повторите с --apply, чтобы записать во «Входящие»")
            return 0
        if not targets:
            _say("отправлять некому")
            return 0
        created, _batch = await queue_many(
            session,
            tenant_id=tenant_id,
            employee_ids=targets,
            kind=KIND,
            title=TITLE,
            body=reminder_body(contest),
            url=URL,
            payload={"campaign": args.campaign, "contest_id": str(contest.id)},
        )
        # Пуш намеренно не планируется: у получателей нет подписки.
        await session.commit()
        _say(f"записано во «Входящие»: {created}")
        log.info("race_push_reminder.sent", campaign=args.campaign, created=created)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

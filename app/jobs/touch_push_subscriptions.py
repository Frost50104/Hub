"""One-shot: подтвердить существующие push-подписки в момент выката.

Гейт свежести (`push_sender.send_to_employee`) шлёт только по подпискам,
подтверждённым за последние `push_freshness_days`. Подтверждает их
`POST /push/subscribe`, который до этого релиза звался ОДИН раз в жизни
устройства, а `last_seen_at` двигался только при успешной отправке — которой
за месяц не случилось ни одной (транспорт был сломан, инцидент 26.08).

Значит на момент выката у всех живых подписок `last_seen_at` — это дата
установки, и гейт выключил бы пуши ровно тогда, когда мы их починили. Джоба
даёт каждой подписке полный срок: дальше её судьбу решает тихая переподписка
при следующем запуске PWA (`web/src/lib/pushRefresh.ts`).

Прогонять ОДИН раз, сразу после выката бэкенда.

    .venv/bin/python -m app.jobs.touch_push_subscriptions            # разбор
    .venv/bin/python -m app.jobs.touch_push_subscriptions --apply    # запись
"""

from __future__ import annotations

import argparse
import asyncio

import structlog
from sqlalchemy import func, select, update

from app import log as log_config
from app.db import bypass_session_factory
from app.models.push_subscription import PushSubscription

log = structlog.get_logger("jobs.touch_push_subscriptions")


async def run(*, apply: bool) -> int:
    """Продлить `last_seen_at` всем подпискам. Возвращает число строк.

    Сессия — ТОЛЬКО bypass-RLS: `push_subscriptions` под политикой
    `push_subscriptions_rls`, а джоба идёт по всем тенантам сразу. Обычная
    сессия без `app.tenant_id` молча обновила бы ноль строк и отрапортовала об
    успехе.
    """
    factory = bypass_session_factory()
    async with factory() as session:
        rows = (
            await session.execute(
                select(
                    PushSubscription.id,
                    PushSubscription.employee_id,
                    PushSubscription.last_seen_at,
                ).order_by(PushSubscription.last_seen_at)
            )
        ).all()
        for row in rows:
            log.info(
                "push_sub.found",
                sub_id=row.id,
                employee_id=str(row.employee_id),
                last_seen_at=row.last_seen_at.isoformat(),
            )
        if not apply:
            log.info("dry_run", subscriptions=len(rows))
            return len(rows)
        await session.execute(update(PushSubscription).values(last_seen_at=func.now()))
        await session.commit()
        log.info("touched", subscriptions=len(rows))
        return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="записать изменения")
    args = parser.parse_args()
    log_config.configure()
    count = asyncio.run(run(apply=args.apply))
    log.info("done", applied=args.apply, subscriptions=count)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

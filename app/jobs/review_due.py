"""Daily cron: напоминание владельцу материала о проверке актуальности.

ТЗ §8.2/§26: у материала есть период актуализации (review_period_months →
next_review_at, выставляется при publish). Когда срок подошёл — владелец
получает `content.review_due`. Анти-дуп: не чаще раза в 7 дней на материал.

Скан — под bypass_rls (cross-tenant), доменная запись уведомлений — в
tenant-scoped сессии соответствующего тенанта (инвариант learn-домена:
bypass только на чтение очередей).

Run via systemd: `signaris-hub[-staging]-review-due.timer` (daily).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select
from sqlalchemy import text as sa_text

from app import log as log_config
from app.db import tenant_scoped_session
from app.models.library import LibraryMaterial

log = structlog.get_logger("jobs.review_due")

ANTI_DUP_WINDOW = timedelta(days=7)


async def _already_reminded(session, material_id, owner_id, since) -> bool:  # noqa: ANN001
    row = await session.execute(
        sa_text(
            "SELECT 1 FROM notifications "
            "WHERE employee_id = :emp AND kind = 'content.review_due' "
            "AND created_at > :since AND payload->>'material_id' = :mid LIMIT 1"
        ),
        {"emp": str(owner_id), "since": since, "mid": str(material_id)},
    )
    return row.scalar_one_or_none() is not None


async def main() -> int:
    log_config.configure()
    now = datetime.now(UTC)
    since = now - ANTI_DUP_WINDOW

    async with tenant_scoped_session(None, bypass_rls=True) as scan:
        due = (
            (
                await scan.execute(
                    select(
                        LibraryMaterial.id,
                        LibraryMaterial.tenant_id,
                        LibraryMaterial.title,
                        LibraryMaterial.owner_id,
                    ).where(
                        LibraryMaterial.status == "published",
                        LibraryMaterial.next_review_at.is_not(None),
                        LibraryMaterial.next_review_at <= now,
                        LibraryMaterial.owner_id.is_not(None),
                    )
                )
            )
            .all()
        )

    log.info("review_due.scanned", due_count=len(due))
    sent = 0
    by_tenant: dict = {}
    for material_id, tenant_id, title, owner_id in due:
        by_tenant.setdefault(tenant_id, []).append((material_id, title, owner_id))

    from app.services.notification_dispatcher import dispatch

    for tenant_id, items in by_tenant.items():
        async with tenant_scoped_session(tenant_id) as session:
            for material_id, title, owner_id in items:
                if await _already_reminded(session, material_id, owner_id, since):
                    continue
                await dispatch(
                    session,
                    tenant_id=tenant_id,
                    employee_id=owner_id,
                    kind="content.review_due",
                    title="Пора проверить документ",
                    body=f"«{title}» — срок актуализации подошёл. Проверьте и обновите материал.",
                    url=f"/learn/library?m={material_id}",
                    payload={"material_id": str(material_id)},
                )
                sent += 1
            await session.commit()

    log.info("review_due.finished", sent=sent)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

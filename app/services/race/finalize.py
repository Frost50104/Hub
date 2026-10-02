"""Финализация предварительных баз — замена ручного «Пересчитать из iiko» утром старта.

База, посчитанная до закрытия своего ретро-окна (`math.baseline_is_preliminary`),
пересчитывается по ПОЛНОМУ окну, когда окно закрылось. Зовут две джобы:
- ночное закрытие (`jobs/race_close.py`, 03:45 МСК) с `through_day=close_day` —
  в ночь перед стартом S окно `[S−28, S−1]` закрылось, и день S−1 только что
  дотянут самим закрытием; это основной путь;
- часовой тик (`jobs/race_sync.py`) с `through_day=вчера`, но только с
  `BASELINE_FINALIZE_FROM_HOUR` — самолечение на случай, если закрытие упало
  (iiko занят дважды): база доедет первым тиком после 04:40, а не через сутки.
  До 04:00 тик финализацию не трогает: день в iiko считается закрытым после
  ночной повторной выгрузки, ради неё закрытие и существует.

Вызовы iiko идут ВНЕ advisory-лока тенанта (инвариант модуля: лок берётся
ПОСЛЕ iiko), поэтому финализация живёт в джобах после `activate_due`, а не
внутри него. Каждый scope — своя транзакция: при сбое откатывается целиком,
база остаётся предварительной, а не половинчатой.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.race import Race, RaceContest
from app.services.iiko import service as iiko_service
from app.services.iiko.client import IikoError, IikoNotConfigured
from app.services.race import iiko_pull
from app.services.race.baselines import preliminary_scopes
from app.services.timefmt import display_tz

log = structlog.get_logger("race.finalize")

# Час display tz, с которого часовой тик вправе финализировать базы: ночное
# закрытие идёт в 03:45 МСК, до него вчерашний день в iiko не считается закрытым.
BASELINE_FINALIZE_FROM_HOUR = 4


@dataclass
class FinalizeReport:
    finalized: list[tuple[UUID, UUID | None]] = field(default_factory=list)
    failed: list[tuple[UUID, UUID | None]] = field(default_factory=list)


async def finalize_baselines(
    session: AsyncSession, *, tenant_id: UUID, through_day: date
) -> FinalizeReport:
    """Пересчитать из iiko все предварительные базы конкурсов `scheduled|active`,
    чьё окно закрылось по `through_day` включительно. Коммитит сама."""
    report = FinalizeReport()
    tz = display_tz()
    contest_ids = list(
        (
            await session.execute(
                select(RaceContest.id).where(
                    RaceContest.tenant_id == tenant_id,
                    RaceContest.status.in_(("scheduled", "active")),
                )
            )
        ).scalars()
    )
    for contest_id in contest_ids:
        scopes = await preliminary_scopes(session, contest_id, through_day=through_day, tz=tz)
        for race_id in scopes:
            # После rollback ORM-объекты протухают — берём их заново на каждый scope.
            contest = await session.get(RaceContest, contest_id)
            race = None if race_id is None else await session.get(Race, race_id)
            if contest is None or (race_id is not None and race is None):
                continue
            try:
                rep = await iiko_pull.compute_baselines(session, contest=contest, race=race)
                await session.commit()
                report.finalized.append((contest_id, race_id))
                log.info(
                    "race.baselines_finalized",
                    tenant_id=str(tenant_id),
                    contest_id=str(contest_id),
                    race_id=None if race_id is None else str(race_id),
                    period_from=str(rep.period_from),
                    period_to=str(rep.period_to),
                    computed=rep.computed,
                    empty=rep.empty,
                    skipped_manual=rep.skipped_manual,
                )
            except (
                iiko_service.IikoBusy,
                IikoError,
                IikoNotConfigured,
                iiko_pull.RaceSyncDisabled,
            ) as e:
                await session.rollback()
                report.failed.append((contest_id, race_id))
                log.warning(
                    "race.baselines_finalize_failed",
                    tenant_id=str(tenant_id),
                    contest_id=str(contest_id),
                    race_id=None if race_id is None else str(race_id),
                    err=str(e),
                )
    return report

"""«Гусиная гонка»: ночное закрытие дня (systemd timer, 00:45 UTC = 03:45 MSK).

`close_day = вчера` по московской дате. На тенант:
1. выгрузка окна `engine.pull_window(through=close_day)` — штатно
   `[close_day − 1, close_day]` (учётный день iiko закрыт, чеки после полуночи
   уже легли), после отказа iiko — от первого дня без снимка (кусками ≤ 14
   дней, commit после каждого); `IikoBusy` — одна повторная попытка через 60 с;
2. `close_day(sales_complete=pulled)` для активных конкурсов: снимки, итоги
   заезда по `ends_on`, следующий заезд; commit. **Выгрузка упала — снимки и
   итоги откладываются** (`race.close_deferred`) до первого закрытия с полной
   выгрузкой: до 17.10 снимки писались по устаревшим данным (три одинаковых
   дня подряд), а итоги заморозились бы по неполным;
3. если следующему заезду нужна база (режим `race`) — `compute_baselines`
   ОТДЕЛЬНО, вне advisory-лока: расчёт ходит в iiko (при упавшей выгрузке
   пропускается — iiko только что отказал);
4. `activate_due` — конкурс со стартом сегодня становится активным;
5. `finalize_baselines(through_day=close_day)` — базы, посчитанные до
   закрытия своего окна (планирование заранее, ручной пересчёт), в ночь
   перед стартом пересчитываются по полному окну; ручной шаг утром не нужен;
6. `last_close_day` в `race_sync_state` — ТОЛЬКО после полной выгрузки:
   иначе `close_stale` хелсчека молчал бы, как 15–17.10.
Пушей здесь нет — их шлёт часовая джоба после 09:00.

Гейты те же, что у race_sync: без них staging тянул бы iiko и двигал
конкурсы, а окружение без кредов падало бы в `failed` каждую ночь.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import structlog
from sqlalchemy import select, text

from app import log as log_config
from app.config import get_settings
from app.db import tenant_scoped_session
from app.models.race import Race, RaceContest
from app.redis_client import close_redis
from app.services.iiko import service as iiko_service
from app.services.iiko.client import IikoError, IikoNotConfigured
from app.services.race import engine, finalize, gate, iiko_pull, read
from app.services.race.math import chunk_period

log = structlog.get_logger("jobs.race_close")

_TENANTS_SQL = text(
    "SELECT DISTINCT tenant_id FROM race_contests WHERE status IN ('scheduled', 'active')"
)
RETRY_SLEEP_SEC = 60.0


async def _pull_with_retry(session, tenant_id, *, day_from, day_to) -> bool:
    """Выгрузить окно кусками ≤ 14 дней; каждый записанный кусок коммитится —
    при сбое на следующем прогресс остаётся, а окно следующей ночи всё равно
    считается от снимков. Любой сбой = «выгрузка неполная» → закрытие
    откладывается целиком."""
    for a, b in chunk_period(day_from, day_to, iiko_pull.BASELINE_WINDOW_DAYS):
        for attempt in (1, 2):
            try:
                report = await iiko_pull.pull_days(
                    session, tenant_id=tenant_id, day_from=a, day_to=b
                )
                await session.commit()
                if report.skipped_empty:
                    return False
                break
            except iiko_service.IikoBusy:
                log.info("race_close.busy", tenant_id=str(tenant_id), attempt=attempt)
                if attempt == 1:
                    await asyncio.sleep(RETRY_SLEEP_SEC)
            except (IikoError, IikoNotConfigured) as e:
                log.warning("race_close.pull_failed", tenant_id=str(tenant_id), err=str(e))
                return False
        else:
            return False  # дважды занят — догоним следующей ночью
    return True


async def _tenant_close(tenant_id, *, close_day, today) -> None:
    async with tenant_scoped_session(tenant_id) as session:
        if not await gate.tenant_enabled(session, tenant_id):
            log.info("race_close.tenant_disabled", tenant_id=str(tenant_id))
            return
        current = await read.current_contest(session, tenant_id)
        if current is not None and current.status in ("active", "scheduled"):
            day_from, day_to = await engine.pull_window(session, current, through=close_day)
        else:
            day_from, day_to = close_day - timedelta(days=1), close_day
        pulled = await _pull_with_retry(session, tenant_id, day_from=day_from, day_to=day_to)
        await session.commit()
        needing_baseline: list = []
        contests = list(
            (
                await session.execute(
                    select(RaceContest).where(
                        RaceContest.tenant_id == tenant_id, RaceContest.status == "active"
                    )
                )
            ).scalars()
        )
        for contest in contests:
            report = await engine.close_day(
                session, contest, close_day=close_day, sales_complete=pulled
            )
            await session.commit()
            log.info(
                "race_close.closed",
                tenant_id=str(tenant_id),
                contest_id=str(contest.id),
                snapshots=report.snapshots,
                finished=[str(r) for r in report.finished_race_ids],
                activated=[str(r) for r in report.activated_race_ids],
                contest_finished=report.contest_finished,
                pulled=pulled,
                pull_from=str(day_from),
                deferred=report.deferred,
                deferred_days=report.deferred_days,
            )
            for race_id in report.races_needing_baseline:
                needing_baseline.append((contest.id, race_id))
        if not pulled:
            log.warning(
                "race_close.iiko_steps_skipped",
                tenant_id=str(tenant_id),
                needing_baseline=len(needing_baseline),
            )
            needing_baseline = []
        for contest_id, race_id in needing_baseline:
            contest = await session.get(RaceContest, contest_id)
            race = await session.get(Race, race_id)
            try:
                rep = await iiko_pull.compute_baselines(session, contest=contest, race=race)
                await session.commit()
                log.info(
                    "race_close.baselines",
                    contest_id=str(contest_id),
                    race_id=str(race_id),
                    computed=rep.computed,
                    empty=rep.empty,
                )
            except (iiko_service.IikoBusy, IikoError, IikoNotConfigured) as e:
                await session.rollback()
                log.warning("race_close.baselines_failed", race_id=str(race_id), err=str(e))
        await engine.activate_due(session, tenant_id, today=today)
        await session.commit()
        if not pulled:
            return
        await finalize.finalize_baselines(session, tenant_id=tenant_id, through_day=close_day)
        await iiko_pull.touch_sync_state(session, tenant_id, close_day=close_day)
        await session.commit()


async def main() -> int:
    log_config.configure()
    settings = get_settings()
    if not settings.race_enabled or not settings.race_sync_enabled:
        log.info("race_close.disabled")
        return 0
    if not iiko_service.is_configured():
        log.info("race_close.iiko_not_configured")
        return 0
    today = engine.today_local()
    close_day = today - timedelta(days=1)
    try:
        async with tenant_scoped_session(None, bypass_rls=True) as scan:
            tenant_ids = [r[0] for r in await scan.execute(_TENANTS_SQL)]
        log.info("race_close.started", tenants=len(tenant_ids), close_day=str(close_day))
        for tenant_id in tenant_ids:
            try:
                await _tenant_close(tenant_id, close_day=close_day, today=today)
            except Exception:  # noqa: BLE001
                log.exception("race_close.tenant_failed", tenant_id=str(tenant_id))
        log.info("race_close.finished")
    finally:
        await close_redis()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

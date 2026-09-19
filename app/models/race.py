"""«Гусиная гонка» — конкурс точек по наполняемости чека (0057).

Инварианты:
- участник = точка `stores` с подразделением iiko (`department_id` — снимок
  `Department.Id` из `shadow_sites.refs`); один участник на подразделение
  (partial-UNIQUE), дубль помечается `excluded (duplicate)`;
- лиги — снимок «групп точек» на момент конкурса (`race_contest_leagues`):
  переименование или перестановка группы позже не перетасует итоги;
- суточная агрегация `race_daily_stats` ключуется ПОДРАЗДЕЛЕНИЕМ, а не
  точкой — переживает смену участника и кормит расчёт базы;
- снимки `race_snapshots` пишет только ночное закрытие и никогда не
  переписывает: по ним график, динамика и рекорды;
- итоги `race_results` заморожены навсегда, даже если дотяжка потом поправит
  суточные цифры;
- `today`/`close_day` считаются в московской дате и передаются явно.
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

CONTEST_STATUSES = ("draft", "scheduled", "active", "finished", "cancelled")
RACE_STATUSES = ("scheduled", "active", "finished")
RACE_LENGTHS = (7, 14)
BASELINE_MODES = ("contest", "race")
BASELINE_SOURCES = ("iiko", "manual")
FINISH_REASONS = ("schedule", "forced")
EXCLUDE_REASONS = ("duplicate", "manual")


class RaceContest(Base):
    __tablename__ = "race_contests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','scheduled','active','finished','cancelled')",
            name="ck_race_contests_status",
        ),
        CheckConstraint("race_length_days IN (7, 14)", name="ck_race_contests_length"),
        CheckConstraint("weeks_total BETWEEN 1 AND 12", name="ck_race_contests_weeks"),
        CheckConstraint(
            "baseline_mode IN ('contest','race')", name="ck_race_contests_baseline_mode"
        ),
        CheckConstraint(
            "baseline_days BETWEEN 7 AND 92", name="ck_race_contests_baseline_days"
        ),
        CheckConstraint("ends_on >= starts_on", name="ck_race_contests_dates"),
        CheckConstraint(
            "(weeks_total * 7) % race_length_days = 0", name="ck_race_contests_divisible"
        ),
        Index("ix_race_contests_tenant_status", "tenant_id", "status"),
        # Одновременно активен не более одного конкурса на тенант.
        Index(
            "uq_race_contests_active",
            "tenant_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    starts_on: Mapped[date] = mapped_column(Date, nullable=False)
    ends_on: Mapped[date] = mapped_column(Date, nullable=False)
    race_length_days: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=7)
    weeks_total: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=4)
    baseline_mode: Mapped[str] = mapped_column(String(8), nullable=False, default="contest")
    baseline_days: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=28)
    created_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("shadow_users.employee_id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RaceContestLeague(Base):
    __tablename__ = "race_contest_leagues"
    __table_args__ = (
        UniqueConstraint("contest_id", "store_group_id", name="uq_race_contest_leagues_group"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    contest_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("race_contests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Снимок `store_groups.id`/`name` — БЕЗ FK: группу могут удалить, лига остаётся.
    store_group_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)


class Race(Base):
    __tablename__ = "races"
    __table_args__ = (
        UniqueConstraint("contest_id", "seq", name="uq_races_contest_seq"),
        CheckConstraint("status IN ('scheduled','active','finished')", name="ck_races_status"),
        CheckConstraint("ends_on >= starts_on", name="ck_races_dates"),
        CheckConstraint(
            "finish_reason IS NULL OR finish_reason IN ('schedule','forced')",
            name="ck_races_finish_reason",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    contest_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("race_contests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    seq: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    starts_on: Mapped[date] = mapped_column(Date, nullable=False)
    # Включительно; досрочное завершение переписывает на день завершения.
    ends_on: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="scheduled")
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finish_reason: Mapped[str | None] = mapped_column(String(16), nullable=True)
    forced_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("shadow_users.employee_id", ondelete="SET NULL"),
        nullable=True,
    )
    # Дедуп пуша «заезд стартовал».
    started_notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class RaceParticipant(Base):
    __tablename__ = "race_participants"
    __table_args__ = (
        UniqueConstraint("contest_id", "store_id", name="uq_race_participants_store"),
        CheckConstraint(
            "exclude_reason IS NULL OR exclude_reason IN ('duplicate','manual','closed')",
            name="ck_race_participants_exclude_reason",
        ),
        # Один живой участник на подразделение iiko.
        Index(
            "uq_race_participants_department",
            "contest_id",
            "department_id",
            unique=True,
            postgresql_where=text("excluded_at IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    contest_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("race_contests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    store_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False
    )
    department_id: Mapped[str] = mapped_column(String(64), nullable=False)
    league_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("race_contest_leagues.id", ondelete="SET NULL"),
        nullable=True,
    )
    excluded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    excluded_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("shadow_users.employee_id", ondelete="SET NULL"),
        nullable=True,
    )
    exclude_reason: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class RaceBaseline(Base):
    __tablename__ = "race_baselines"
    __table_args__ = (
        # `race_id IS NULL` = база на весь конкурс; NULLS NOT DISTINCT (PG15+),
        # иначе UNIQUE не сработал бы на двух строках «конкурсной» базы.
        UniqueConstraint(
            "contest_id",
            "store_id",
            "race_id",
            name="uq_race_baselines_scope",
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint("source IN ('iiko','manual')", name="ck_race_baselines_source"),
        CheckConstraint("value IS NULL OR value > 0", name="ck_race_baselines_value"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    contest_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("race_contests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    store_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False
    )
    race_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("races.id", ondelete="CASCADE"), nullable=True
    )
    value: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    source: Mapped[str] = mapped_column(String(8), nullable=False)
    receipts: Mapped[int | None] = mapped_column(Integer, nullable=True)
    items: Mapped[float | None] = mapped_column(Numeric(14, 3), nullable=True)
    period_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    set_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("shadow_users.employee_id", ondelete="SET NULL"),
        nullable=True,
    )
    set_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class RaceDailyStat(Base):
    """Чеки и позиции подразделения iiko за учётный день (replace-window)."""

    __tablename__ = "race_daily_stats"
    __table_args__ = (Index("ix_race_daily_stats_day", "tenant_id", "day"),)

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    department_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    receipts: Mapped[int] = mapped_column(Integer, nullable=False)
    items: Mapped[float] = mapped_column(Numeric(14, 3), nullable=False)
    pulled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class RaceSnapshot(Base):
    """Закрытие дня: накопленные с начала заезда цифры и позиция точки."""

    __tablename__ = "race_snapshots"
    __table_args__ = (
        UniqueConstraint("race_id", "store_id", "day", name="uq_race_snapshots_day"),
        Index("ix_race_snapshots_race_day", "race_id", "day"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    race_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("races.id", ondelete="CASCADE"), nullable=False
    )
    store_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False
    )
    day: Mapped[date] = mapped_column(Date, nullable=False)
    receipts_cum: Mapped[int] = mapped_column(Integer, nullable=False)
    items_cum: Mapped[float] = mapped_column(Numeric(14, 3), nullable=False)
    avg: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    base: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    pct: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    cells: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    needs_baseline: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_record: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    record_notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class RaceResult(Base):
    """Замороженный итог точки в гонке."""

    __tablename__ = "race_results"
    __table_args__ = (UniqueConstraint("race_id", "store_id", name="uq_race_results_store"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    race_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("races.id", ondelete="CASCADE"), nullable=False
    )
    store_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False
    )
    department_id: Mapped[str] = mapped_column(String(64), nullable=False)
    league_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("race_contest_leagues.id", ondelete="SET NULL"),
        nullable=True,
    )
    base: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    receipts: Mapped[int] = mapped_column(Integer, nullable=False)
    items: Mapped[float] = mapped_column(Numeric(14, 3), nullable=False)
    avg: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    pct: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    cells: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    needs_baseline: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    place: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    place_in_league: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    frozen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class RaceSyncState(Base):
    """Диагностика выгрузки по тенанту: экран админа и `as_of` трека."""

    __tablename__ = "race_sync_state"

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    last_pull_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_close_day: Mapped[date | None] = mapped_column(Date, nullable=True)

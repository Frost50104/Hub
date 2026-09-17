"""«Гусиная гонка»: конкурсы, гонки, участники, база, суточная агрегация, снимки, итоги

Revision ID: 0057
Revises: 0056
Create Date: 2026-09-17

Заявка UPPETIT (ТЗ 03.09.2026): соревнование точек по наполняемости чека
(среднее число позиций в чеке) на данных iiko. План —
`~/.claude/plans/uppetit-hazy-giraffe.md`.

Девять таблиц под обычной per-tenant RLS. Смысловые решения, которые видно в
схеме:
- `race_participants.department_id` — снимок `Department.Id` из
  `shadow_sites.refs`, partial-UNIQUE `(contest_id, department_id) WHERE
  excluded_at IS NULL`: один живой участник на подразделение iiko (4 пары
  магазинов-дублей делят одно подразделение);
- `race_contest_leagues` — снимок «групп точек» без FK: удаление группы не
  трогает лиги прошедшего конкурса;
- `race_baselines` — UNIQUE `(contest, store, race_id) NULLS NOT DISTINCT`:
  `race_id IS NULL` = база на весь конкурс, иначе — на заезд (PG15+);
- `race_daily_stats` — PK по (tenant, подразделение, день): переживает смену
  участника и кормит расчёт базы;
- `race_snapshots`/`race_results` — «что видели люди», не переписываются;
- `race_sync_state` — диагностика выгрузки на тенант;
- `public_share_tokens.scope` расширяется значением `race` (ТВ-ссылка,
  `entity_id = tenant_id`).

Миграция аддитивная — катится до деплоя кода без окна `UndefinedColumn`.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0057"
down_revision: str | None = "0056"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

RLS_POLICY = (
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid "
    "OR current_setting('app.bypass_rls', true) = 'on'"
)

TABLES = (
    "race_contests",
    "race_contest_leagues",
    "races",
    "race_participants",
    "race_baselines",
    "race_daily_stats",
    "race_snapshots",
    "race_results",
    "race_sync_state",
)


def _uuid():
    return postgresql.UUID(as_uuid=True)


def _tenant():
    return sa.Column("tenant_id", _uuid(), nullable=False)


def _ts(name: str, *, nullable: bool = True, default_now: bool = False):
    kw = {"nullable": nullable}
    if default_now:
        kw["server_default"] = sa.text("now()")
    return sa.Column(name, sa.DateTime(timezone=True), **kw)


def _employee_fk(name: str):
    return sa.Column(
        name, _uuid(), sa.ForeignKey("shadow_users.employee_id", ondelete="SET NULL"), nullable=True
    )


def _rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY {table}_rls ON {table} USING ({RLS_POLICY})")


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")

    op.create_table(
        "race_contests",
        sa.Column("id", _uuid(), primary_key=True),
        _tenant(),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=False),
        sa.Column("race_length_days", sa.SmallInteger(), nullable=False, server_default="7"),
        sa.Column("weeks_total", sa.SmallInteger(), nullable=False, server_default="4"),
        sa.Column("baseline_mode", sa.String(8), nullable=False, server_default="contest"),
        sa.Column("baseline_days", sa.SmallInteger(), nullable=False, server_default="28"),
        _employee_fk("created_by"),
        _ts("created_at", nullable=False, default_now=True),
        _ts("updated_at", nullable=False, default_now=True),
        _ts("scheduled_at"),
        _ts("finished_at"),
        _ts("cancelled_at"),
        sa.CheckConstraint(
            "status IN ('draft','scheduled','active','finished','cancelled')",
            name="ck_race_contests_status",
        ),
        sa.CheckConstraint("race_length_days IN (7, 14)", name="ck_race_contests_length"),
        sa.CheckConstraint("weeks_total BETWEEN 1 AND 12", name="ck_race_contests_weeks"),
        sa.CheckConstraint(
            "baseline_mode IN ('contest','race')", name="ck_race_contests_baseline_mode"
        ),
        sa.CheckConstraint("baseline_days BETWEEN 7 AND 92", name="ck_race_contests_baseline_days"),
        sa.CheckConstraint("ends_on >= starts_on", name="ck_race_contests_dates"),
        sa.CheckConstraint(
            "(weeks_total * 7) % race_length_days = 0", name="ck_race_contests_divisible"
        ),
    )
    op.create_index("ix_race_contests_tenant_id", "race_contests", ["tenant_id"])
    op.create_index("ix_race_contests_tenant_status", "race_contests", ["tenant_id", "status"])
    op.execute(
        "CREATE UNIQUE INDEX uq_race_contests_active ON race_contests (tenant_id) "
        "WHERE status = 'active'"
    )

    op.create_table(
        "race_contest_leagues",
        sa.Column("id", _uuid(), primary_key=True),
        _tenant(),
        sa.Column(
            "contest_id",
            _uuid(),
            sa.ForeignKey("race_contests.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("store_group_id", _uuid(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.UniqueConstraint("contest_id", "store_group_id", name="uq_race_contest_leagues_group"),
    )
    op.create_index("ix_race_contest_leagues_tenant_id", "race_contest_leagues", ["tenant_id"])
    op.create_index("ix_race_contest_leagues_contest_id", "race_contest_leagues", ["contest_id"])

    op.create_table(
        "races",
        sa.Column("id", _uuid(), primary_key=True),
        _tenant(),
        sa.Column(
            "contest_id",
            _uuid(),
            sa.ForeignKey("race_contests.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("seq", sa.SmallInteger(), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="scheduled"),
        _ts("finished_at"),
        sa.Column("finish_reason", sa.String(16), nullable=True),
        _employee_fk("forced_by"),
        _ts("started_notified_at"),
        _ts("created_at", nullable=False, default_now=True),
        sa.UniqueConstraint("contest_id", "seq", name="uq_races_contest_seq"),
        sa.CheckConstraint("status IN ('scheduled','active','finished')", name="ck_races_status"),
        sa.CheckConstraint("ends_on >= starts_on", name="ck_races_dates"),
        sa.CheckConstraint(
            "finish_reason IS NULL OR finish_reason IN ('schedule','forced')",
            name="ck_races_finish_reason",
        ),
    )
    op.create_index("ix_races_tenant_id", "races", ["tenant_id"])
    op.create_index("ix_races_contest_id", "races", ["contest_id"])

    op.create_table(
        "race_participants",
        sa.Column("id", _uuid(), primary_key=True),
        _tenant(),
        sa.Column(
            "contest_id",
            _uuid(),
            sa.ForeignKey("race_contests.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "store_id", _uuid(), sa.ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("department_id", sa.String(64), nullable=False),
        sa.Column(
            "league_id",
            _uuid(),
            sa.ForeignKey("race_contest_leagues.id", ondelete="SET NULL"),
            nullable=True,
        ),
        _ts("excluded_at"),
        _employee_fk("excluded_by"),
        sa.Column("exclude_reason", sa.String(16), nullable=True),
        _ts("created_at", nullable=False, default_now=True),
        sa.UniqueConstraint("contest_id", "store_id", name="uq_race_participants_store"),
        sa.CheckConstraint(
            "exclude_reason IS NULL OR exclude_reason IN ('duplicate','manual')",
            name="ck_race_participants_exclude_reason",
        ),
    )
    op.create_index("ix_race_participants_tenant_id", "race_participants", ["tenant_id"])
    op.create_index("ix_race_participants_contest_id", "race_participants", ["contest_id"])
    op.execute(
        "CREATE UNIQUE INDEX uq_race_participants_department ON race_participants "
        "(contest_id, department_id) WHERE excluded_at IS NULL"
    )

    op.create_table(
        "race_baselines",
        sa.Column("id", _uuid(), primary_key=True),
        _tenant(),
        sa.Column(
            "contest_id",
            _uuid(),
            sa.ForeignKey("race_contests.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "store_id", _uuid(), sa.ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("race_id", _uuid(), sa.ForeignKey("races.id", ondelete="CASCADE"), nullable=True),
        sa.Column("value", sa.Numeric(10, 4), nullable=True),
        sa.Column("source", sa.String(8), nullable=False),
        sa.Column("receipts", sa.Integer(), nullable=True),
        sa.Column("items", sa.Numeric(14, 3), nullable=True),
        sa.Column("period_from", sa.Date(), nullable=True),
        sa.Column("period_to", sa.Date(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        _employee_fk("set_by"),
        _ts("set_at", nullable=False, default_now=True),
        sa.CheckConstraint("source IN ('iiko','manual')", name="ck_race_baselines_source"),
        sa.CheckConstraint("value IS NULL OR value > 0", name="ck_race_baselines_value"),
    )
    op.create_index("ix_race_baselines_tenant_id", "race_baselines", ["tenant_id"])
    op.create_index("ix_race_baselines_contest_id", "race_baselines", ["contest_id"])
    # PG15+: два NULL в race_id считаются равными — вторая «конкурсная» база невозможна.
    op.execute(
        "ALTER TABLE race_baselines ADD CONSTRAINT uq_race_baselines_scope "
        "UNIQUE NULLS NOT DISTINCT (contest_id, store_id, race_id)"
    )

    op.create_table(
        "race_daily_stats",
        sa.Column("tenant_id", _uuid(), primary_key=True),
        sa.Column("department_id", sa.String(64), primary_key=True),
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("receipts", sa.Integer(), nullable=False),
        sa.Column("items", sa.Numeric(14, 3), nullable=False),
        _ts("pulled_at", nullable=False, default_now=True),
    )
    op.create_index("ix_race_daily_stats_day", "race_daily_stats", ["tenant_id", "day"])

    op.create_table(
        "race_snapshots",
        sa.Column("id", _uuid(), primary_key=True),
        _tenant(),
        sa.Column(
            "race_id", _uuid(), sa.ForeignKey("races.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "store_id", _uuid(), sa.ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("receipts_cum", sa.Integer(), nullable=False),
        sa.Column("items_cum", sa.Numeric(14, 3), nullable=False),
        sa.Column("avg", sa.Numeric(10, 4), nullable=True),
        sa.Column("base", sa.Numeric(10, 4), nullable=True),
        sa.Column("pct", sa.Numeric(8, 2), nullable=True),
        sa.Column("cells", sa.SmallInteger(), nullable=False),
        sa.Column("needs_baseline", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_record", sa.Boolean(), nullable=False, server_default=sa.false()),
        _ts("record_notified_at"),
        sa.UniqueConstraint("race_id", "store_id", "day", name="uq_race_snapshots_day"),
    )
    op.create_index("ix_race_snapshots_tenant_id", "race_snapshots", ["tenant_id"])
    op.create_index("ix_race_snapshots_race_day", "race_snapshots", ["race_id", "day"])

    op.create_table(
        "race_results",
        sa.Column("id", _uuid(), primary_key=True),
        _tenant(),
        sa.Column(
            "race_id", _uuid(), sa.ForeignKey("races.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "store_id", _uuid(), sa.ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("department_id", sa.String(64), nullable=False),
        sa.Column(
            "league_id",
            _uuid(),
            sa.ForeignKey("race_contest_leagues.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("base", sa.Numeric(10, 4), nullable=True),
        sa.Column("receipts", sa.Integer(), nullable=False),
        sa.Column("items", sa.Numeric(14, 3), nullable=False),
        sa.Column("avg", sa.Numeric(10, 4), nullable=True),
        sa.Column("pct", sa.Numeric(8, 2), nullable=True),
        sa.Column("cells", sa.SmallInteger(), nullable=False),
        sa.Column("needs_baseline", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("place", sa.SmallInteger(), nullable=True),
        sa.Column("place_in_league", sa.SmallInteger(), nullable=True),
        _ts("frozen_at", nullable=False, default_now=True),
        sa.UniqueConstraint("race_id", "store_id", name="uq_race_results_store"),
    )
    op.create_index("ix_race_results_tenant_id", "race_results", ["tenant_id"])
    op.create_index("ix_race_results_race_id", "race_results", ["race_id"])

    op.create_table(
        "race_sync_state",
        sa.Column("tenant_id", _uuid(), primary_key=True),
        _ts("last_pull_at"),
        _ts("last_success_at"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_close_day", sa.Date(), nullable=True),
    )

    for table in TABLES:
        _rls(table)

    # ТВ-ссылка гонки — тот же механизм, что публичные ссылки задач/проектов.
    op.drop_constraint("ck_public_share_tokens_scope", "public_share_tokens", type_="check")
    op.create_check_constraint(
        "ck_public_share_tokens_scope",
        "public_share_tokens",
        "scope IN ('task','project','race')",
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("DELETE FROM public_share_tokens WHERE scope = 'race'")
    op.drop_constraint("ck_public_share_tokens_scope", "public_share_tokens", type_="check")
    op.create_check_constraint(
        "ck_public_share_tokens_scope", "public_share_tokens", "scope IN ('task','project')"
    )
    for table in reversed(TABLES):
        op.execute(f"DROP POLICY IF EXISTS {table}_rls ON {table}")
    op.drop_table("race_sync_state")
    op.drop_index("ix_race_results_race_id", table_name="race_results")
    op.drop_index("ix_race_results_tenant_id", table_name="race_results")
    op.drop_table("race_results")
    op.drop_index("ix_race_snapshots_race_day", table_name="race_snapshots")
    op.drop_index("ix_race_snapshots_tenant_id", table_name="race_snapshots")
    op.drop_table("race_snapshots")
    op.drop_index("ix_race_daily_stats_day", table_name="race_daily_stats")
    op.drop_table("race_daily_stats")
    op.execute("ALTER TABLE race_baselines DROP CONSTRAINT IF EXISTS uq_race_baselines_scope")
    op.drop_index("ix_race_baselines_contest_id", table_name="race_baselines")
    op.drop_index("ix_race_baselines_tenant_id", table_name="race_baselines")
    op.drop_table("race_baselines")
    op.execute("DROP INDEX IF EXISTS uq_race_participants_department")
    op.drop_index("ix_race_participants_contest_id", table_name="race_participants")
    op.drop_index("ix_race_participants_tenant_id", table_name="race_participants")
    op.drop_table("race_participants")
    op.drop_index("ix_races_contest_id", table_name="races")
    op.drop_index("ix_races_tenant_id", table_name="races")
    op.drop_table("races")
    op.drop_index("ix_race_contest_leagues_contest_id", table_name="race_contest_leagues")
    op.drop_index("ix_race_contest_leagues_tenant_id", table_name="race_contest_leagues")
    op.drop_table("race_contest_leagues")
    op.execute("DROP INDEX IF EXISTS uq_race_contests_active")
    op.drop_index("ix_race_contests_tenant_status", table_name="race_contests")
    op.drop_index("ix_race_contests_tenant_id", table_name="race_contests")
    op.drop_table("race_contests")

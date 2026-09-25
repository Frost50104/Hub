"""0063: кадровые данные из auth (шаг 16d) — состояние синка, правило K, архив отделов.

Кадровый процесс переезжает в auth (решение владельца 21.09): Hub читает ключ
`hr` из выгрузки штата и снимок справочников `/api/products/org-directory`,
применяет их и замораживает свою правку, пока организация `authoritative`.
План — ~/.claude/plans/pure-plotting-hartmanis.md, контракт —
docs/handoffs/HUB_TASK_hr_in_auth_16d.md.

- `hr_sync_state` — строка на тенант: состояние заморозки из последнего ПОЛНОГО
  снимка справочников (сбой сети её не снимает), ручное окно каткатa, порядок
  прогонов (монотонные метки снимка — кнопка и воркер не применяют старый снимок
  поверх нового), отчёт, отложенный набор предохранителя. RLS как у всех
  доменных таблиц.
- `departments.archived_at` — auth архивирует отделы, у нас колонки не было
  (согласовано auth, ANSWER 25.09 §3.3).
- `shadow_users.inactive_runs` / `inactive_since` — счётчик правила K («учётка
  отключена в auth K прогонов подряд → архив»). Поля синка, как `hub_role`.
- `employee_profiles.auth_deactivated_name` — имя учётки в момент архива по K.
  Возврат снимает архив, только если имя совпало: auth оживляет отключённую
  учётку приглашением на ту же почту, и без сверки новый человек на ящике
  уволенного получил бы его историю.
- причина архива `auth_deactivated` — вход СОХРАНЯЕТ (как `auto_inactivity`).

`ADD COLUMN … DEFAULT` константой — только метаданные, но `ALTER shadow_users`
ждёт замок самой нагруженной таблицы: держит её синк дольше 5 с — миграция
падает по `lock_timeout`, выкат повторяем. Без таймаута ALTER встал бы в очередь
замков и остановил все запросы.

Revision ID: 0063
Revises: 0062
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0063"
down_revision: str | None = "0062"
branch_labels = None
depends_on = None

RLS_POLICY = (
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid "
    "OR current_setting('app.bypass_rls', true) = 'on'"
)

TABLE = "hr_sync_state"

_REASON_CHECK = "ck_employee_profiles_archive_reason"
_REASONS_NEW = (
    "archive_reason IS NULL OR "
    "archive_reason IN ('manual', 'auto_inactivity', 'auth_deleted', 'auth_deactivated')"
)
_REASONS_OLD = (
    "archive_reason IS NULL OR "
    "archive_reason IN ('manual', 'auto_inactivity', 'auth_deleted')"
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table(
        TABLE,
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), primary_key=True),
        # Заморозка — из последнего ПОЛНОГО снимка справочников.
        sa.Column("in_snapshot", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "authoritative", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("snapshot_at", sa.DateTime(timezone=True), nullable=True),
        # С какого момента организация authoritative — алерт «заморожено, но
        # правки auth не применяются дольше часа» (тенант не в списке применения).
        sa.Column("authoritative_since", sa.DateTime(timezone=True), nullable=True),
        # Ручное окно каткатa: пишет ТОЛЬКО CLI `app.jobs.hr_cutover`.
        sa.Column(
            "cutover_freeze", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("cutover_since", sa.DateTime(timezone=True), nullable=True),
        # Порядок прогонов: метка скачивания последнего прогона и последнего
        # применения — прогон со снимком не новее уже обработанного пропускается.
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_mode", sa.String(16), nullable=True),
        # Только числа и id — без ПДн.
        sa.Column("last_report", postgresql.JSONB(), nullable=True),
        # Предохранитель: отложенный набор и его отпечаток.
        sa.Column("pending_fingerprint", sa.String(64), nullable=True),
        sa.Column("pending_ops", postgresql.JSONB(), nullable=True),
        sa.Column("pending_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("blocked_reason", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY {TABLE}_rls ON {TABLE} USING ({RLS_POLICY})")

    op.add_column(
        "departments", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "shadow_users",
        sa.Column(
            "inactive_runs", sa.SmallInteger(), nullable=False, server_default=sa.text("0")
        ),
    )
    op.add_column(
        "shadow_users",
        sa.Column("inactive_since", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "employee_profiles",
        sa.Column("auth_deactivated_name", sa.String(255), nullable=True),
    )
    op.drop_constraint(_REASON_CHECK, "employee_profiles", type_="check")
    op.create_check_constraint(_REASON_CHECK, "employee_profiles", _REASONS_NEW)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    # Старый CHECK новой причины не знает. `auto_inactivity` — единственная
    # прежняя причина, которая так же сохраняет вход.
    op.execute(
        "UPDATE employee_profiles SET archive_reason = 'auto_inactivity' "
        "WHERE archive_reason = 'auth_deactivated'"
    )
    op.drop_constraint(_REASON_CHECK, "employee_profiles", type_="check")
    op.create_check_constraint(_REASON_CHECK, "employee_profiles", _REASONS_OLD)
    op.drop_column("employee_profiles", "auth_deactivated_name")
    op.drop_column("shadow_users", "inactive_since")
    op.drop_column("shadow_users", "inactive_runs")
    op.drop_column("departments", "archived_at")
    op.execute(f"DROP POLICY IF EXISTS {TABLE}_rls ON {TABLE}")
    op.drop_table(TABLE)

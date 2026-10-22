"""0066: конвейер видео урока — статус, роль и производные `media_files`,
состав сборки, транскрипты, раскадровка, очередь заданий.

Заявка UPPETIT (PETRPOPOV-8, ТЗ 22.09) и решения владельца 22.10
(`~/.claude/plans/a-b-validated-aurora.md`): субтитры и расшифровка (A),
чистовик с ужатыми паузами (B), сборка из нескольких записей, монтаж с гусём
вместо спикера и вставками поверх голоса (C2). Всё считает отдельный воркер
`signaris-hub-media` (ffmpeg + наш Whisper), гусь — Hedra.

`media_files`:
- `kind` получает `'subtitle'` — VTT отдаётся той же ручкой `/api/media/{id}`
  (X-Accel, `Content-Type` из `mime`), второй путь отдачи не нужен. Колонка
  `String(8)`, поэтому именно `subtitle`, а не `subtitles`;
- `status` — `ready|processing|failed`: нормализация MOV/WebM и сборка из
  записей идут НА МЕСТЕ, пока файл никто не мог смотреть (ручка отдачи
  отвечает 409 до `ready`); после `ready` файл под `media_id` неизменяем, как
  и прежде;
- `role` — `content|part|insert|scene`: части сборки, вставки и сцена гуся в
  уроки не вставляются и в `usage` не считаются;
- `source_media_id` + `variant` (`cleaned|composed`) — производные файлы
  всегда НОВЫЕ строки (гейт досмотра делит покрытие на `duration_sec`
  конкретной строки).

Новые таблицы: `media_parts` (состав сборки, `RESTRICT` на часть),
`media_transcripts` (сегменты с таймкодами, отдельно от горячей
`media_files`), `media_storyboard` (раскадровка и вставки — правки автора
должны переживать закрытие шторки), `media_jobs` (очередь воркера: claim под
`FOR UPDATE SKIP LOCKED`, аренда `lease_until`, частичный UNIQUE активного
задания гасит двойной клик).

RLS — ENABLE + FORCE на всех четырёх; воркер сканирует под bypass, доменную
запись делает в tenant-scoped сессии. Аддитивно: старый код новых колонок не
читает, правило двух деплоев не применяется.

Revision ID: 0066
Revises: 0065
Create Date: 2026-10-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0066"
down_revision = "0065"
branch_labels = None
depends_on = None

RLS_POLICY = (
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid "
    "OR current_setting('app.bypass_rls', true) = 'on'"
)

_KIND_OLD = "kind IN ('image', 'video', 'pdf')"
_KIND_NEW = "kind IN ('image', 'video', 'pdf', 'subtitle')"
_UUID = postgresql.UUID(as_uuid=True)
_TS = sa.DateTime(timezone=True)


def _rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY {table}_rls ON {table} USING ({RLS_POLICY})")


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")

    # ── media_files ────────────────────────────────────────────────────────
    op.drop_constraint("ck_media_files_kind", "media_files", type_="check")
    op.create_check_constraint("ck_media_files_kind", "media_files", _KIND_NEW)
    op.add_column(
        "media_files",
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'ready'")),
    )
    op.create_check_constraint(
        "ck_media_files_status", "media_files", "status IN ('ready', 'processing', 'failed')"
    )
    op.add_column(
        "media_files",
        sa.Column("role", sa.String(16), nullable=False, server_default=sa.text("'content'")),
    )
    op.create_check_constraint(
        "ck_media_files_role", "media_files", "role IN ('content', 'part', 'insert', 'scene')"
    )
    op.add_column(
        "media_files",
        sa.Column(
            "source_media_id",
            _UUID,
            sa.ForeignKey("media_files.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column("media_files", sa.Column("variant", sa.String(16), nullable=True))
    op.create_check_constraint(
        "ck_media_files_variant",
        "media_files",
        "variant IS NULL OR variant IN ('cleaned', 'composed')",
    )
    op.execute(
        "CREATE INDEX ix_media_files_source ON media_files (source_media_id) "
        "WHERE source_media_id IS NOT NULL"
    )

    # ── media_parts ────────────────────────────────────────────────────────
    op.create_table(
        "media_parts",
        sa.Column(
            "merged_media_id",
            _UUID,
            sa.ForeignKey("media_files.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("position", sa.SmallInteger(), primary_key=True),
        sa.Column("tenant_id", _UUID, nullable=False),
        sa.Column(
            "source_media_id",
            _UUID,
            sa.ForeignKey("media_files.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("trim_start_sec", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column("trim_end_sec", sa.Float(), nullable=True),
        sa.CheckConstraint("position >= 0", name="ck_media_parts_position"),
        sa.CheckConstraint("trim_start_sec >= 0", name="ck_media_parts_trim"),
    )
    op.create_index("ix_media_parts_tenant", "media_parts", ["tenant_id"])
    op.create_index("ix_media_parts_source", "media_parts", ["source_media_id"])
    _rls("media_parts")

    # ── media_transcripts ──────────────────────────────────────────────────
    op.create_table(
        "media_transcripts",
        sa.Column(
            "media_id",
            _UUID,
            sa.ForeignKey("media_files.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("tenant_id", _UUID, nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("language", sa.String(8), nullable=False, server_default=sa.text("'ru'")),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("segments", postgresql.JSONB(), nullable=False),
        sa.Column("duration_sec", sa.Float(), nullable=True),
        sa.Column("source_transcript_media_id", _UUID, nullable=True),
        sa.Column("created_at", _TS, nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", _TS, nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_media_transcripts_tenant", "media_transcripts", ["tenant_id"])
    _rls("media_transcripts")

    # ── media_storyboard ───────────────────────────────────────────────────
    op.create_table(
        "media_storyboard",
        sa.Column(
            "media_id",
            _UUID,
            sa.ForeignKey("media_files.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("tenant_id", _UUID, nullable=False),
        sa.Column("face_track", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column(
            "segments_auto", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'")
        ),
        sa.Column("segments", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("inserts", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("goose_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "edited_by",
            _UUID,
            sa.ForeignKey("shadow_users.employee_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("params", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", _TS, nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", _TS, nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_media_storyboard_tenant", "media_storyboard", ["tenant_id"])
    _rls("media_storyboard")

    # ── media_jobs ─────────────────────────────────────────────────────────
    op.create_table(
        "media_jobs",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("tenant_id", _UUID, nullable=False),
        sa.Column(
            "media_id", _UUID, sa.ForeignKey("media_files.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'queued'")),
        sa.Column("params", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("result", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default=sa.text("2")),
        sa.Column("priority", sa.SmallInteger(), nullable=False, server_default=sa.text("100")),
        sa.Column("run_after", _TS, nullable=False, server_default=sa.text("now()")),
        sa.Column("lease_until", _TS, nullable=True),
        sa.Column("worker_id", sa.String(64), nullable=True),
        sa.Column(
            "cancel_requested", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "requested_by",
            _UUID,
            sa.ForeignKey("shadow_users.employee_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "output_media_id",
            _UUID,
            sa.ForeignKey("media_files.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", _TS, nullable=False, server_default=sa.text("now()")),
        sa.Column("started_at", _TS, nullable=True),
        sa.Column("finished_at", _TS, nullable=True),
        sa.CheckConstraint(
            "kind IN ('merge', 'normalize', 'transcribe', 'analyze', 'cleanup', "
            "'compose', 'avatar_test')",
            name="ck_media_jobs_kind",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'done', 'failed', 'cancelled')",
            name="ck_media_jobs_status",
        ),
        sa.CheckConstraint("attempts >= 0 AND max_attempts >= 1", name="ck_media_jobs_attempts"),
    )
    op.create_index("ix_media_jobs_tenant", "media_jobs", ["tenant_id"])
    op.execute("CREATE INDEX ix_media_jobs_media ON media_jobs (media_id, created_at DESC)")
    op.execute(
        "CREATE INDEX ix_media_jobs_queue ON media_jobs (priority, created_at) "
        "WHERE status IN ('queued', 'running')"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_media_jobs_active ON media_jobs (media_id, kind) "
        "WHERE status IN ('queued', 'running')"
    )
    _rls("media_jobs")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    # FORCE RLS: без bypass DELETE молча удалил бы 0 строк, и старый CHECK
    # `kind` упал бы на первом же VTT.
    op.execute("SET LOCAL app.bypass_rls = 'on'")
    for table in ("media_jobs", "media_storyboard", "media_transcripts", "media_parts"):
        op.execute(f"DROP POLICY IF EXISTS {table}_rls ON {table}")
        op.drop_table(table)
    # Субтитры регенерируемы; файлы VTT на диске остаются (сборщика сирот нет).
    op.execute("DELETE FROM media_files WHERE kind = 'subtitle'")
    op.execute("DROP INDEX IF EXISTS ix_media_files_source")
    op.drop_constraint("ck_media_files_variant", "media_files", type_="check")
    op.drop_column("media_files", "variant")
    op.drop_column("media_files", "source_media_id")
    op.drop_constraint("ck_media_files_role", "media_files", type_="check")
    op.drop_column("media_files", "role")
    op.drop_constraint("ck_media_files_status", "media_files", type_="check")
    op.drop_column("media_files", "status")
    op.drop_constraint("ck_media_files_kind", "media_files", type_="check")
    op.create_check_constraint("ck_media_files_kind", "media_files", _KIND_OLD)

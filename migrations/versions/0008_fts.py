"""Full-text search infra: pg_trgm, unaccent, tsvector + GIN (3.6.11)

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-29

Adds Postgres FTS support:
- `pg_trgm` / `unaccent` extensions (idempotent CREATE IF NOT EXISTS).
- `tasks.search_vector` — STORED GENERATED tsvector over title (weight A)
  + description (weight B), Russian dictionary. Auto-maintained by Postgres
  on every insert/update — no app-side logic.
- GIN index on `tasks.search_vector` for `@@` queries.
- Trigram index on `tasks.title` for substring/fuzzy matches.
- GIN tsvector on `task_comments.body` (not stored — comments are smaller
  and rarely edited; on-the-fly to_tsvector keeps the table cheap).

CREATE EXTENSION requires superuser. Hub uses migrate-role with SUPERUSER
(see `bootstrap-vps.sh`), so this runs cleanly. Production-ready: extensions
are tenant-wide and don't affect existing data shape.
"""

from __future__ import annotations

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")

    op.execute(
        """
        ALTER TABLE tasks
        ADD COLUMN search_vector tsvector
        GENERATED ALWAYS AS (
            setweight(to_tsvector('russian', coalesce(title, '')), 'A') ||
            setweight(to_tsvector('russian', coalesce(description, '')), 'B')
        ) STORED
        """
    )
    op.execute(
        "CREATE INDEX ix_tasks_search_vector ON tasks USING GIN(search_vector)"
    )
    op.execute(
        "CREATE INDEX ix_tasks_title_trgm ON tasks USING GIN(title gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX ix_task_comments_body_fts "
        "ON task_comments USING GIN(to_tsvector('russian', body))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_task_comments_body_fts")
    op.execute("DROP INDEX IF EXISTS ix_tasks_title_trgm")
    op.execute("DROP INDEX IF EXISTS ix_tasks_search_vector")
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS search_vector")
    # Не дропаем расширения — могут использоваться другими таблицами в будущем.

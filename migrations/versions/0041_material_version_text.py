"""Извлечённый текст версии материала — material_versions.extracted_text

Revision ID: 0041
Revises: 0040
Create Date: 2026-08-21

До этого извлечённый текст docx/pdf жил ТОЛЬКО в search_documents.body_text, и
`_reindex` (любой PATCH/смена статуса материала) затирал его пустым значением —
на проде 86 из 181 опубликованных материалов остались без текста для поиска и
RAG. Теперь воркер пишет текст в версию (независимо от статуса материала), а
индекс берёт его оттуда при каждой переиндексации.

Две NULL-колонки — безопасно для окна деплоя (alembic до рестарта): старый код
их не знает. RLS-политика таблицы уже есть (0022).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0041"
down_revision: str | None = "0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("material_versions", sa.Column("extracted_text", sa.Text(), nullable=True))
    op.add_column(
        "material_versions",
        sa.Column("extracted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("material_versions", "extracted_at")
    op.drop_column("material_versions", "extracted_text")

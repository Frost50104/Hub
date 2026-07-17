"""Поддержка единого поискового индекса search_documents (Ф1).

Инварианты:
- индексируются ТОЛЬКО published-объекты (заголовки черновиков не должны
  светиться в выдаче) — archive/unpublish удаляет строку;
- body_text жёстко обрезается (лимиты tsvector: позиции >16383 отбрасываются,
  вектор ≤1 МБ);
- вызывается из lifecycle-переходов и из обновления опубликованного объекта.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.search_document import SearchDocument

_BODY_LIMIT = 200_000
_SNIPPET_LIMIT = 2_000


async def upsert_document(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    object_type: str,
    object_id: UUID,
    title: str,
    url_path: str,
    snippet: str | None = None,
    body_text: str | None = None,
    audience_id: UUID | None = None,
    published_at: datetime | None = None,
) -> None:
    stmt = pg_insert(SearchDocument).values(
        tenant_id=tenant_id,
        object_type=object_type,
        object_id=object_id,
        title=title[:512],
        snippet=(snippet or None) and snippet[:_SNIPPET_LIMIT],
        body_text=(body_text or None) and body_text[:_BODY_LIMIT],
        audience_id=audience_id,
        published_at=published_at,
        url_path=url_path[:512],
    )
    await db.execute(
        stmt.on_conflict_do_update(
            constraint="uq_search_documents_object",
            set_={
                "title": stmt.excluded.title,
                "snippet": stmt.excluded.snippet,
                "body_text": stmt.excluded.body_text,
                "audience_id": stmt.excluded.audience_id,
                "published_at": stmt.excluded.published_at,
                "url_path": stmt.excluded.url_path,
                "updated_at": stmt.excluded.updated_at,
            },
        )
    )


async def delete_document(db: AsyncSession, *, object_type: str, object_id: UUID) -> None:
    await db.execute(
        delete(SearchDocument).where(
            SearchDocument.object_type == object_type,
            SearchDocument.object_id == object_id,
        )
    )

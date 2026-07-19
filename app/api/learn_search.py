"""Поиск по learn-домену (Ф5, ТЗ §10): единый индекс search_documents.

FTS по russian-словарю (websearch_to_tsquery) с ILIKE-fallback для
неморфологизируемых запросов; выдача фильтруется аудиторией. Запросы
логируются в search_queries (отчёт «что ищут» — аналитика).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from signaris_auth import Principal
from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import enforce_rate_limit, get_db, require_auth
from app.models.engagement import SearchQueryLog
from app.models.search_document import SearchDocument
from app.services.audience_resolver import visible_filter
from app.services.org_scope import get_profile

router = APIRouter(tags=["learn-search"])

OBJECT_TYPE_LABEL = {
    "library_material": "Библиотека",
    "news_post": "Новость",
    "survey": "Опрос",
    "course": "Курс",
    "product": "Ассортимент",
}


class LearnSearchHit(BaseModel):
    object_type: str
    object_id: UUID
    title: str
    snippet: str | None
    url_path: str
    type_label: str


class LearnSearchResponse(BaseModel):
    query: str
    total: int
    hits: list[LearnSearchHit]


@router.get("/learn/search", response_model=LearnSearchResponse)
async def learn_search(
    q: str = Query(min_length=2, max_length=200),
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> LearnSearchResponse:
    await enforce_rate_limit(
        bucket="search",
        employee_id=str(principal.employee_id),
        limit=60,
        window_sec=60,
    )
    profile = await get_profile(db, principal)
    profile_id = profile.id if profile else None
    query = q.strip()

    fts = text(
        "search_vector @@ websearch_to_tsquery('russian', :q)"
    ).bindparams(q=query)
    stmt = (
        select(SearchDocument)
        .where(
            visible_filter(SearchDocument, profile_id or UUID(int=0)),
            or_(fts, SearchDocument.title.ilike(f"%{query}%")),
        )
        .order_by(
            text(
                "ts_rank(search_vector, websearch_to_tsquery('russian', :rq)) DESC"
            ).bindparams(rq=query),
            SearchDocument.published_at.desc().nulls_last(),
        )
        .limit(30)
    )
    docs = (await db.execute(stmt)).scalars().all()

    db.add(
        SearchQueryLog(
            tenant_id=principal.tenant_id,
            profile_id=profile_id,
            query=query[:512],
            results_count=len(docs),
        )
    )
    await db.commit()

    return LearnSearchResponse(
        query=query,
        total=len(docs),
        hits=[
            LearnSearchHit(
                object_type=d.object_type,
                object_id=d.object_id,
                title=d.title,
                snippet=d.snippet,
                url_path=d.url_path,
                type_label=OBJECT_TYPE_LABEL.get(d.object_type, d.object_type),
            )
            for d in docs
        ],
    )

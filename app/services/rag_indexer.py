"""RAG-индексация (Ф6): чанки поверх search_documents.

Источник знаний ассистента = поисковый индекс (только published-контент,
audience_id уже денормализован) — RAG не может увидеть черновик или чужую
аудиторию по построению. Reconcile-модель: воркер сверяет rag_chunks с
search_documents по (embedding_model, source_updated_at) и достраивает /
переиндексирует / подчищает устаревшее.
"""

from __future__ import annotations

import structlog
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai import RagChunk
from app.models.search_document import SearchDocument
from app.services.llm.base import LLMProvider

log = structlog.get_logger("rag_indexer")

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 150
MAX_CHUNKS_PER_DOC = 40


def chunk_text(source: str, *, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Скользящее окно с попыткой резать по границе предложения. Pure."""
    cleaned = " ".join(source.split())
    if not cleaned:
        return []
    if len(cleaned) <= size:
        return [cleaned]
    chunks: list[str] = []
    start = 0
    while start < len(cleaned) and len(chunks) < MAX_CHUNKS_PER_DOC:
        end = min(start + size, len(cleaned))
        if end < len(cleaned):
            # Ищем ближайшую границу предложения в хвосте окна.
            window = cleaned[start:end]
            cut = max(window.rfind(". "), window.rfind("! "), window.rfind("? "))
            if cut > size // 2:
                end = start + cut + 1
        chunks.append(cleaned[start:end].strip())
        if end >= len(cleaned):
            break
        start = max(end - overlap, start + 1)
    return [c for c in chunks if c]


def _doc_text(doc: SearchDocument) -> str:
    return " ".join(filter(None, [doc.title, doc.snippet, doc.body_text]))


async def reindex_document(
    session: AsyncSession, provider: LLMProvider, doc: SearchDocument
) -> int:
    """Перестроить чанки документа. → сколько чанков записано."""
    chunks = chunk_text(_doc_text(doc))
    await session.execute(
        delete(RagChunk).where(
            RagChunk.object_type == doc.object_type, RagChunk.object_id == doc.object_id
        )
    )
    if not chunks:
        return 0
    embeddings = await provider.embed(chunks)
    for i, (chunk, emb) in enumerate(zip(chunks, embeddings, strict=True)):
        session.add(
            RagChunk(
                tenant_id=doc.tenant_id,
                object_type=doc.object_type,
                object_id=doc.object_id,
                chunk_index=i,
                audience_id=doc.audience_id,
                title=doc.title,
                url_path=doc.url_path,
                content=chunk,
                embedding=emb,
                embedding_model=provider.embed_model,
                source_updated_at=doc.updated_at,
            )
        )
    return len(chunks)


async def reconcile(
    session: AsyncSession, provider: LLMProvider, *, limit: int = 10
) -> dict[str, int]:
    """Догнать индекс: новые/изменённые документы + мусор от unpublished."""
    stale_docs = (
        (
            await session.execute(
                select(SearchDocument)
                .where(
                    ~select(RagChunk.id)
                    .where(
                        RagChunk.object_type == SearchDocument.object_type,
                        RagChunk.object_id == SearchDocument.object_id,
                        RagChunk.embedding_model == provider.embed_model,
                        RagChunk.source_updated_at >= SearchDocument.updated_at,
                    )
                    .exists()
                )
                .order_by(SearchDocument.updated_at)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    indexed = 0
    for doc in stale_docs:
        indexed += await reindex_document(session, provider, doc)

    # Чанки без живого документа (контент снят с публикации) — подчистить.
    orphans = await session.execute(
        text(
            "DELETE FROM rag_chunks rc WHERE NOT EXISTS ("
            "SELECT 1 FROM search_documents sd "
            "WHERE sd.object_type = rc.object_type AND sd.object_id = rc.object_id)"
        )
    )
    return {
        "docs": len(stale_docs),
        "chunks": indexed,
        "orphans_deleted": orphans.rowcount or 0,
    }

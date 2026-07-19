"""Extraction + RAG воркер (Ф6) — ОТДЕЛЬНЫЙ systemd-сервис.

Не живёт в uvicorn-процессе осознанно (adversarial-ревью плана): парсинг
PDF/DOCX — CPU-bound и заморозил бы API (workers=1). Здесь парсинг уходит
в thread pool, цикл — каждые 30 секунд:

1. text_extraction_jobs (pending) → извлечение текста файла (pypdf /
   python-docx / plain) → search_documents.body_text — «поиск по
   содержимому файлов» начинает находить документы.
2. RAG-reconcile (если AI настроен): search_documents → rag_chunks
   с эмбеддингами; без ключа шаг тихо пропускается.

Скан очередей — bypass; доменная запись — в tenant-scoped сессиях.
Run via systemd: `signaris-hub[-staging]-extraction.service` (Restart=always).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import structlog
from sqlalchemy import select, text

from app import log as log_config
from app.db import tenant_scoped_session
from app.models.library import LibraryMaterial
from app.models.search_document import TextExtractionJob
from app.services.library_storage import absolute_path
from app.services.llm import LLMEmbeddingsUnsupported, LLMNotConfigured, get_provider
from app.services.rag_indexer import reconcile
from app.services.search_indexer import upsert_document

log = structlog.get_logger("workers.extraction")

POLL_SEC = 30
BATCH = 10
MAX_ATTEMPTS = 3
TEXT_LIMIT = 200_000

_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _extract_text_sync(path: Path, mime: str) -> str:
    """CPU-bound парсинг — зовётся через asyncio.to_thread."""
    if mime == "application/pdf":
        from pypdf import PdfReader

        reader = PdfReader(path)
        pages = [page.extract_text() or "" for page in reader.pages[:200]]
        return "\n".join(pages)[:TEXT_LIMIT]
    if mime == _DOCX_MIME:
        import docx

        document = docx.Document(str(path))
        return "\n".join(p.text for p in document.paragraphs)[:TEXT_LIMIT]
    if mime.startswith("text/"):
        return path.read_text(errors="ignore")[:TEXT_LIMIT]
    raise ValueError(f"Извлечение текста для {mime} не поддерживается")


async def _process_extraction_batch() -> int:
    async with tenant_scoped_session(None, bypass_rls=True) as scan:
        jobs = (
            (
                await scan.execute(
                    select(TextExtractionJob)
                    .where(
                        TextExtractionJob.status == "pending",
                        TextExtractionJob.attempts < MAX_ATTEMPTS,
                    )
                    .order_by(TextExtractionJob.created_at)
                    .limit(BATCH)
                )
            )
            .scalars()
            .all()
        )
        job_specs = [
            (j.id, j.tenant_id, j.object_id, j.storage_key, j.mime) for j in jobs
        ]

    done = 0
    for job_id, tenant_id, object_id, storage_key, mime in job_specs:
        async with tenant_scoped_session(tenant_id) as session:
            job = await session.get(TextExtractionJob, job_id)
            if job is None or job.status != "pending":
                continue
            try:
                path = absolute_path(storage_key)
                body_text = await asyncio.to_thread(_extract_text_sync, path, mime)
                material = await session.get(LibraryMaterial, object_id)
                if material is not None and material.status == "published":
                    await upsert_document(
                        session,
                        tenant_id=material.tenant_id,
                        object_type="library_material",
                        object_id=material.id,
                        title=material.title,
                        snippet=material.description,
                        body_text=body_text,
                        audience_id=material.audience_id,
                        published_at=material.published_at,
                        url_path=f"/learn/library?m={material.id}",
                    )
                job.status = "done"
                job.error = None
                done += 1
            except Exception as e:  # noqa: BLE001 — джоба не должна ронять цикл
                job.attempts += 1
                job.error = str(e)[:500]
                if job.attempts >= MAX_ATTEMPTS:
                    job.status = "failed"
                log.warning(
                    "extraction.job_failed",
                    job_id=job_id,
                    attempts=job.attempts,
                    err=str(e)[:200],
                )
            await session.commit()
    return done


async def _process_rag() -> None:
    try:
        provider = get_provider()
    except LLMNotConfigured:
        return  # AI не настроен — extraction работает, RAG ждёт ключа
    async with tenant_scoped_session(None, bypass_rls=True) as scan:
        tenant_ids = [
            r[0]
            for r in await scan.execute(
                text("SELECT DISTINCT tenant_id FROM search_documents")
            )
        ]
    for tenant_id in tenant_ids:
        async with tenant_scoped_session(tenant_id) as session:
            try:
                stats = await reconcile(session, provider, limit=5)
            except LLMEmbeddingsUnsupported:
                # Провайдер без embeddings (DeepSeek): ассистент работает
                # через лексический retrieval, вект-индекс не строим.
                return
            await session.commit()
            if stats["docs"] or stats["orphans_deleted"]:
                log.info("rag.reconciled", tenant_id=str(tenant_id), **stats)


async def main() -> None:
    log_config.configure()
    log.info("extraction.worker_started", poll_sec=POLL_SEC)
    while True:
        try:
            processed = await _process_extraction_batch()
            if processed:
                log.info("extraction.batch_done", jobs=processed)
            await _process_rag()
        except Exception as e:  # noqa: BLE001 — цикл живёт всегда
            log.error("extraction.cycle_failed", err=str(e)[:300])
        await asyncio.sleep(POLL_SEC)


if __name__ == "__main__":
    asyncio.run(main())

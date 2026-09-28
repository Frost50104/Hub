"""Бэкфилл воркера извлечения: упавшее переставляется только при старте (28.09).

До правки цикл ставил версию с упавшей джобой в очередь заново каждые ~90 с:
три попытки → failed → новая джоба. 47 файлов, которые не открывались,
накопили по 335 тыс. строк в базах прода и staging."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, select

from app.db import tenant_scoped_session
from app.models.library import LibraryMaterial, MaterialVersion
from app.models.search_document import TextExtractionJob
from app.workers import extraction

pytestmark = pytest.mark.integration

# Бэкфилл берёт 300 САМЫХ СТАРЫХ версий общей тестовой базы — наши должны
# оказаться в начале очереди, иначе тест зависит от соседей.
_LONG_AGO = datetime(2000, 1, 1, tzinfo=UTC)


async def _pending(keys: list[str]) -> list[str]:
    async with tenant_scoped_session(None, bypass_rls=True) as s:
        rows = await s.execute(
            select(TextExtractionJob.storage_key).where(
                TextExtractionJob.storage_key.in_(keys),
                TextExtractionJob.status == "pending",
            )
        )
        return sorted(r[0] for r in rows)


async def test_failed_version_is_retried_only_on_start(tenant_id: uuid.UUID, _fresh_engine) -> None:
    tag = uuid.uuid4().hex[:8]
    failed_key = f"{tenant_id}/learn/materials/{tag}/v1-xlsx"
    fresh_key = f"{tenant_id}/learn/materials/{tag}/v2-xlsx"
    keys = [failed_key, fresh_key]
    material_id: uuid.UUID | None = None
    try:
        # Бэкфилл открывает СВОЮ сессию — данные обязаны быть закоммичены.
        async with tenant_scoped_session(tenant_id) as s:
            material = LibraryMaterial(tenant_id=tenant_id, title="Остатки", kind="file")
            s.add(material)
            await s.flush()
            material_id = material.id
            for version_no, key in enumerate(keys, start=1):
                s.add(
                    MaterialVersion(
                        material_id=material.id,
                        tenant_id=tenant_id,
                        version_no=version_no,
                        storage_key=key,
                        file_name="xlsx",
                        mime=extraction._XLSX_MIME,
                        size_bytes=10,
                        created_at=_LONG_AGO,
                    )
                )
            s.add(
                TextExtractionJob(
                    tenant_id=tenant_id,
                    object_type="library_material",
                    object_id=material.id,
                    storage_key=failed_key,
                    mime=extraction._XLSX_MIME,
                    status="failed",
                    attempts=extraction.MAX_ATTEMPTS,
                    error="openpyxl does not support  file format",
                )
            )
            await s.commit()

        # Цикл: упавшая версия в очередь не встаёт, новая — встаёт.
        await extraction._enqueue_backfill(retry_failed=False)
        assert await _pending(keys) == [fresh_key]

        # Старт процесса: упавшая пробуется снова, у новой дубля нет.
        await extraction._enqueue_backfill(retry_failed=True)
        assert await _pending(keys) == sorted(keys)
    finally:
        async with tenant_scoped_session(None, bypass_rls=True) as s:
            await s.execute(
                delete(TextExtractionJob).where(TextExtractionJob.storage_key.in_(keys))
            )
            if material_id is not None:
                await s.execute(
                    delete(MaterialVersion).where(MaterialVersion.material_id == material_id)
                )
                await s.execute(delete(LibraryMaterial).where(LibraryMaterial.id == material_id))
            await s.commit()

"""Отдача инструкций по работе в Hub — по подписанной ссылке.

Ручка без `require_auth` намеренно: страница открывается новой вкладкой, а
навигация не несёт заголовка `Authorization`. Роль решает НЕ здесь, а в
`services/guides.py::guides_for_role` — там, где ссылка выдаётся (`GET /api/me`).
Подпись — та же машинерия, что у медиа уроков, ключ разный.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, Response

from app.config import get_settings
from app.services.guides import GUIDE_FILES, guide_file_path, verify_guide_signature

router = APIRouter(tags=["guides"])


@router.get("/guides/{kind}")
async def serve_guide(
    kind: str,
    e: int = Query(...),
    s: str = Query(..., max_length=64),
) -> Response:
    if not verify_guide_signature(kind, e, s):
        raise HTTPException(status_code=403, detail="Ссылка недействительна или истекла")

    settings = get_settings()
    if not settings.media_accel_enabled:
        path = guide_file_path(kind)
        if not path.is_file():
            raise HTTPException(status_code=410, detail="Файл инструкции отсутствует")
        return FileResponse(path, media_type="text/html")

    # nginx отдаёт файл сам (sendfile) по internal-локации; ЗАГОЛОВКИ ответа
    # берутся ИЗ НЕЁ — там же живёт CSP, разрешающая инструкции её собственный
    # inline-скрипт (поиск по документу, отметки о прочтении).
    return Response(
        status_code=200,
        headers={
            "X-Accel-Redirect": f"/_guides/{GUIDE_FILES[kind]}",
            "Content-Type": "text/html; charset=utf-8",
            # Имя файла не хешируется: с длинным кэшем обновлённая инструкция
            # не доехала бы до тех, кто её уже открывал.
            "Cache-Control": "private, no-cache",
        },
    )

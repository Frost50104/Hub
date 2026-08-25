"""Отдача инструкций по работе в Hub — по подписанной ссылке.

Ручка без `require_auth` намеренно: страница открывается новой вкладкой, а
навигация не несёт заголовка `Authorization`. Роль решает НЕ здесь, а в
`services/guides.py::guides_for_role` — там, где ссылка выдаётся (`GET /api/me`).
Подпись — та же машинерия, что у медиа уроков, ключ разный.
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse, HTMLResponse, Response

from app.config import get_settings
from app.services.guides import GUIDE_FILES, guide_file_path, verify_guide_signature

router = APIRouter(tags=["guides"])

# Страница «ссылка устарела». Отдаём HTML, а не JSON-ошибку: адрес инструкции
# живёт в адресной строке отдельной вкладки, его закладывают и открывают из
# истории — а ссылка подписана на несколько часов. `{"detail": …}` в такой
# момент выглядит поломкой продукта, и уйти с него некуда: в PWA обвязки нет,
# у новой вкладки пустая история. Инлайновые стили проходят серверную CSP
# (`style-src 'self' 'unsafe-inline'`), скриптов здесь нет вовсе.
_EXPIRED_HTML = """<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ссылка на инструкцию устарела</title></head>
<body style="margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
background:#08080E;color:#F0F0F5;font:400 16px/1.5 system-ui,-apple-system,sans-serif">
<main style="max-width:420px;padding:32px;text-align:center">
<h1 style="margin:0 0 12px;font-size:22px;font-weight:700">Ссылка устарела</h1>
<p style="margin:0 0 24px;color:rgba(240,240,245,.62)">
Ссылка на инструкцию действует несколько часов. Откройте её заново из профиля —
адрес обновится сам.</p>
<a href="/settings/account" style="display:inline-block;padding:12px 20px;border-radius:999px;
background:#FFB200;color:#08080E;font-weight:600;text-decoration:none">Открыть из профиля</a>
</main></body></html>"""


@router.get("/guides/{kind}")
async def serve_guide(
    kind: str,
    e: int = Query(...),
    s: str = Query(..., max_length=64),
) -> Response:
    if not verify_guide_signature(kind, e, s):
        return HTMLResponse(_EXPIRED_HTML, status_code=403)

    settings = get_settings()
    if not settings.media_accel_enabled:
        path = guide_file_path(kind)
        if not path.is_file():
            return HTMLResponse(_EXPIRED_HTML, status_code=410)
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

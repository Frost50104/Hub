"""POST /api/diag — диагностика обновления приложения с устройства.

Разбор 25.09 («Обновить» на десктопе идёт 30 с) занял форензику nginx-логов
за неделю: с устройства не приходило ничего. Теперь страница присылает
состояние регистрации service worker'а и тайминги каждого нажатия «Обновить»
(`web/src/lib/swDiag.ts`), а здесь это строка `client_diag` в журнале:
`journalctl -u signaris-hub | grep client_diag`. Таблицы нет — журнала
достаточно, пока разборы единичные.

Ручка узкая: тело валидируется схемой с `extra="forbid"`, ответ 204, частота —
30 в час на человека (`sw_hung` — раз на загрузку страницы, `update_click` —
раз на клик). `require_auth_any()`, как у `/api/me`: подсказка про зависший
браузер видна и principal без hub-роли.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, Response, status
from signaris_auth import Principal

from app.deps import enforce_rate_limit, require_auth_any
from app.schemas.diag import SwDiagIn

log = structlog.get_logger()

router = APIRouter(tags=["diag"])

DIAG_RATE_LIMIT = 30
DIAG_RATE_WINDOW_SEC = 3600


@router.post("/diag", status_code=status.HTTP_204_NO_CONTENT)
async def post_diag(
    body: SwDiagIn,
    principal: Principal = Depends(require_auth_any()),
) -> Response:
    await enforce_rate_limit(
        bucket="diag:send",
        employee_id=str(principal.employee_id),
        limit=DIAG_RATE_LIMIT,
        window_sec=DIAG_RATE_WINDOW_SEC,
    )
    # Тело — ВЛОЖЕННЫМ полем `diag`, не `**body`: ключ `event` внутри уронил
    # бы вызов (`TypeError: multiple values for keyword argument 'event'`).
    log.info(
        "client_diag",
        kind=body.kind,
        employee_id=str(principal.employee_id),
        tenant_id=str(principal.tenant_id),
        diag=body.model_dump(),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)

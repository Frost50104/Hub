"""Sid-sync consumer (Hub, Phase 2 SLO) — instant cascade в продуктовом API.

Опрашивает фид ревокации SSO-сессий signaris-auth (`GET /api/products/revoked-sids`)
и добавляет ревокнутые `sso_session_id`'ы в shared `RevokedSidStore`
(см. `app/deps.py`). `require_auth` на каждом запросе проверяет JWT-claim
`signaris:sid` против этого store → если sid в нём, 401 мгновенно
(≤ poll-интервал, обычно 30 сек), без ожидания 15-мин access-TTL.

Курсор хранится в `sync_state` (key='sid_revocations'), та же таблица что и
для deletion-sync (отдельный ключ).
"""

from __future__ import annotations

import structlog
from signaris_auth.sid_sync import run_sid_sync_worker
from sqlalchemy import text

from app.config import get_settings
from app.db import tenant_scoped_session
from app.deps import get_revoked_sid_store

log = structlog.get_logger("sid_sync")
_CURSOR_KEY = "sid_revocations"


async def _load_cursor() -> int:
    async with tenant_scoped_session(None, bypass_rls=True) as session:
        row = await session.execute(
            text("SELECT cursor FROM sync_state WHERE key = :k"),
            {"k": _CURSOR_KEY},
        )
        value = row.scalar_one_or_none()
        if value is None:
            await session.execute(
                text(
                    "INSERT INTO sync_state (key, cursor) VALUES (:k, 0) "
                    "ON CONFLICT (key) DO NOTHING"
                ),
                {"k": _CURSOR_KEY},
            )
            await session.commit()
            return 0
        return int(value)


async def _save_cursor(seq: int) -> None:
    async with tenant_scoped_session(None, bypass_rls=True) as session:
        await session.execute(
            text(
                "INSERT INTO sync_state (key, cursor) VALUES (:k, :s) "
                "ON CONFLICT (key) DO UPDATE SET cursor = EXCLUDED.cursor"
            ),
            {"k": _CURSOR_KEY, "s": seq},
        )
        await session.commit()


async def start_worker() -> None:
    settings = get_settings()
    if not settings.signaris_service_key:
        log.warning("sid_sync.no_service_key")
        return
    await run_sid_sync_worker(
        store=get_revoked_sid_store(),
        base_url=settings.signaris_auth_base_url,
        service_key=settings.signaris_service_key,
        load_cursor=_load_cursor,
        save_cursor=_save_cursor,
        poll_sec=settings.sid_sync_poll_sec,
        enabled=settings.sid_sync_enabled,
    )

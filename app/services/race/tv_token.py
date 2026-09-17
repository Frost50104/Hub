"""Публичная ссылка ТВ-панели: `public_share_tokens` со scope `race`.

`entity_id = tenant_id` — ТВ показывает «гонку», а не «конкурс №3»: ссылка
переживает конкурсы и не требует перенастройки телевизора каждые четыре
недели. Живых ссылок может быть несколько (индекс не unique).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.share import PublicShareToken
from app.services import audit

SCOPE = "race"


def build_tv_url(token: UUID) -> str:
    base = get_settings().public_base_url.rstrip("/")
    return f"{base}/p/race/{token}"


async def list_tv_tokens(session: AsyncSession, tenant_id: UUID) -> list[PublicShareToken]:
    rows = await session.execute(
        select(PublicShareToken)
        .where(
            PublicShareToken.tenant_id == tenant_id,
            PublicShareToken.scope == SCOPE,
            PublicShareToken.revoked_at.is_(None),
        )
        .order_by(PublicShareToken.created_at.desc())
    )
    return list(rows.scalars())


async def create_tv_token(
    session: AsyncSession, *, tenant_id: UUID, actor_id: UUID
) -> PublicShareToken:
    row = PublicShareToken(
        tenant_id=tenant_id, scope=SCOPE, entity_id=tenant_id, created_by=actor_id
    )
    session.add(row)
    await session.flush()
    audit.record(
        session,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="access_change",
        object_type="race_tv_link",
        object_id=row.id,
        object_label="ТВ-ссылка гонки создана",
    )
    return row


async def revoke_tv_token(
    session: AsyncSession, *, tenant_id: UUID, token: UUID, actor_id: UUID
) -> bool:
    row = (
        await session.execute(
            select(PublicShareToken).where(
                PublicShareToken.tenant_id == tenant_id,
                PublicShareToken.scope == SCOPE,
                PublicShareToken.token == token,
            )
        )
    ).scalar_one_or_none()
    if row is None or row.revoked_at is not None:
        return False
    row.revoked_at = datetime.now(UTC)
    audit.record(
        session,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="delete",
        object_type="race_tv_link",
        object_id=row.id,
        object_label="ТВ-ссылка гонки отозвана",
    )
    return True

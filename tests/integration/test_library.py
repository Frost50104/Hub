"""Integration-тесты библиотеки (Ф1): индексер, ack-семантика, hook уведомлений."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.library import _effective_ack_version, _not_acked
from app.models.audience import Audience, AudienceRule
from app.models.employee_profile import EmployeeProfile
from app.models.library import LibraryMaterial, MaterialAcknowledgement
from app.models.notification import Notification
from app.models.org import Position
from app.models.search_document import SearchDocument
from app.services.audience_resolver import recalc_profile
from app.services.learn_notify import notify_new_audience_members
from app.services.search_indexer import delete_document, upsert_document
from tests.integration.conftest import make_principal

pytestmark = pytest.mark.integration


async def _mk_material(db: AsyncSession, tenant_id: uuid.UUID, **kw) -> LibraryMaterial:
    material = LibraryMaterial(
        tenant_id=tenant_id,
        title=kw.pop("title", "Регламент возвратов"),
        kind=kw.pop("kind", "file"),
        **kw,
    )
    db.add(material)
    await db.flush()
    return material


async def test_indexer_upsert_and_delete(db: AsyncSession, tenant_id: uuid.UUID):
    material = await _mk_material(db, tenant_id, description="Как оформить возврат")
    await upsert_document(
        db,
        tenant_id=tenant_id,
        object_type="library_material",
        object_id=material.id,
        title=material.title,
        snippet=material.description,
        url_path=f"/learn/library?m={material.id}",
    )
    doc = (
        await db.execute(
            select(SearchDocument).where(SearchDocument.object_id == material.id)
        )
    ).scalar_one()
    assert doc.title == "Регламент возвратов"

    # Повторный upsert обновляет, не дублирует.
    await upsert_document(
        db,
        tenant_id=tenant_id,
        object_type="library_material",
        object_id=material.id,
        title="Регламент возвратов v2",
        url_path=f"/learn/library?m={material.id}",
    )
    db.expire(doc)  # raw-upsert обновил строку мимо identity map
    docs = (
        (
            await db.execute(
                select(SearchDocument).where(SearchDocument.object_id == material.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(docs) == 1 and docs[0].title == "Регламент возвратов v2"

    # FTS-вектор (STORED GENERATED) реально ищется по русской морфологии.
    from sqlalchemy import text as sa_text

    hit = await db.execute(
        sa_text(
            "SELECT id FROM search_documents WHERE object_id = :oid "
            "AND search_vector @@ websearch_to_tsquery('russian', 'возвраты')"
        ),
        {"oid": str(material.id)},
    )
    assert hit.scalar_one_or_none() is not None

    await delete_document(db, object_type="library_material", object_id=material.id)
    assert (
        await db.execute(
            select(SearchDocument.id).where(SearchDocument.object_id == material.id)
        )
    ).scalar_one_or_none() is None


async def test_ack_semantics_re_ack_versions(db: AsyncSession, tenant_id: uuid.UUID):
    profile = EmployeeProfile(tenant_id=tenant_id, email="u@t.ru", full_name="Юзер")
    db.add(profile)
    await db.flush()

    material = await _mk_material(db, tenant_id, current_version_no=1)
    assert _effective_ack_version(material) == 1

    db.add(
        MaterialAcknowledgement(
            material_id=material.id,
            version_no=1,
            profile_id=profile.id,
            tenant_id=tenant_id,
        )
    )
    await db.flush()

    # re_ack=false: ack любой версии закрывает материал.
    material.re_ack_on_new_version = False
    material.current_version_no = 2
    assert await _not_acked(db, material, [profile.id]) == []

    # re_ack=true: нужна подпись именно текущей (2-й) версии.
    material.re_ack_on_new_version = True
    assert await _not_acked(db, material, [profile.id]) == [profile.id]

    db.add(
        MaterialAcknowledgement(
            material_id=material.id,
            version_no=2,
            profile_id=profile.id,
            tenant_id=tenant_id,
        )
    )
    await db.flush()
    assert await _not_acked(db, material, [profile.id]) == []


async def test_granted_hook_notifies_pending_ack(
    db: AsyncSession, tenant_id: uuid.UUID, monkeypatch
):
    # Пуш в фоне не нужен в тесте — оставляем только in-app запись.
    from app.services import notification_dispatcher

    monkeypatch.setattr(notification_dispatcher, "schedule_push", lambda **kw: None)

    seller_pos = Position(tenant_id=tenant_id, name="Продавец")
    db.add(seller_pos)
    await db.flush()

    principal = make_principal(tenant_id, email="new@t.ru")
    from signaris_auth.shadow import upsert_shadow_tenant, upsert_shadow_user

    await upsert_shadow_tenant(db, principal, table="shadow_tenants")
    await upsert_shadow_user(db, principal, table="shadow_users")
    profile = EmployeeProfile(
        tenant_id=tenant_id,
        employee_id=principal.employee_id,
        email="new@t.ru",
        full_name="Новичок",
    )
    db.add(profile)
    await db.flush()

    audience = Audience(tenant_id=tenant_id)
    db.add(audience)
    await db.flush()
    db.add(
        AudienceRule(
            tenant_id=tenant_id,
            audience_id=audience.id,
            mode="include",
            position_ids=[seller_pos.id],
        )
    )
    await _mk_material(
        db,
        tenant_id,
        audience_id=audience.id,
        requires_acknowledgement=True,
        status="published",
        current_version_no=1,
    )
    await db.flush()

    # Пока новичок не продавец — не в аудитории, уведомлений нет.
    diffs = await recalc_profile(db, profile)
    await notify_new_audience_members(db, diffs)
    assert (
        await db.execute(
            select(Notification.id).where(
                Notification.employee_id == principal.employee_id
            )
        )
    ).scalar_one_or_none() is None

    # Назначили должность → попал в аудиторию → library.ack_required.
    profile.position_id = seller_pos.id
    await db.flush()
    diffs = await recalc_profile(db, profile)
    await notify_new_audience_members(db, diffs)
    await db.flush()  # session factory с autoflush=False

    notif = (
        await db.execute(
            select(Notification).where(Notification.employee_id == principal.employee_id)
        )
    ).scalar_one()
    assert notif.kind == "library.ack_required"
    assert "Регламент возвратов" in notif.body

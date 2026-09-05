"""Integration-тесты библиотеки (Ф1): индексер, ack-семантика, hook уведомлений."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.library import _effective_ack_version, _not_acked, ack_deadline_for
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


async def test_ack_deadline_counts_from_access_grant(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Попавший в аудиторию позже публикации получает свои дни целиком."""
    from datetime import UTC, datetime, timedelta

    published = datetime(2026, 8, 1, tzinfo=UTC)
    material = await _mk_material(
        db,
        tenant_id,
        requires_acknowledgement=True,
        ack_deadline_days=7,
        published_at=published,
        status="published",
    )

    # Доступ был с публикации — дедлайн от неё.
    assert ack_deadline_for(material, None) == published + timedelta(days=7)
    assert ack_deadline_for(material, published - timedelta(days=3)) == published + timedelta(
        days=7
    )

    # Доступ выдан позже — отсчёт от выдачи, иначе дедлайн уже просрочен.
    granted = datetime(2026, 8, 10, tzinfo=UTC)
    assert ack_deadline_for(material, granted) == granted + timedelta(days=7)

    # Без срока ознакомления дедлайна нет вовсе.
    material.ack_deadline_days = None
    assert ack_deadline_for(material, granted) is None


async def test_signed_download_link_for_ios(
    db: AsyncSession, tenant_id: uuid.UUID, tmp_path, monkeypatch
):
    """Фикс iOS (02.09): «Скачать файл» ведёт окно на подписанный https-адрес.

    Оверлей window.open в standalone-PWA не переходит на blob-URL — белый
    about:blank. Ссылку выдаёт авторизованная ручка (она же фиксирует
    открытие для ack-гейта), отдача — по HMAC без Bearer; подпись привязана
    к материалу И версии."""
    from urllib.parse import parse_qs, urlparse

    from fastapi import HTTPException

    from app.api.library import material_download_link, serve_material_file
    from app.config import get_settings
    from app.models.library import MaterialVersion, ViewHistory
    from tests.integration.test_courses import _mk_member

    monkeypatch.setattr(get_settings(), "attachments_root", tmp_path)
    member, profile = await _mk_member(
        db, tenant_id, email=f"dl-{uuid.uuid4().hex[:6]}@t.ru"
    )
    material = await _mk_material(
        db, tenant_id, title="Бланк заказа", status="published", current_version_no=1
    )
    storage_key = f"{tenant_id}/learn/blank.xlsx"
    db.add(
        MaterialVersion(
            material_id=material.id,
            tenant_id=tenant_id,
            version_no=1,
            storage_key=storage_key,
            file_name="blank.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            size_bytes=4,
        )
    )
    await db.flush()
    dest = tmp_path / storage_key
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"PK\x03\x04")
    await db.commit()

    link = await material_download_link(material.id, None, member, db)
    parsed = urlparse(link["url"])
    q = parse_qs(parsed.query)
    assert parsed.path == f"/api/learn/library/materials/{material.id}/file"

    # Выдача ссылки = открытие: ack-гейт «сначала откройте» удовлетворён.
    opened = (
        await db.execute(
            select(ViewHistory).where(
                ViewHistory.profile_id == profile.id,
                ViewHistory.object_id == material.id,
            )
        )
    ).scalar_one_or_none()
    assert opened is not None

    resp = await serve_material_file(
        material.id, v=int(q["v"][0]), e=int(q["e"][0]), s=q["s"][0]
    )
    assert str(resp.path) == str(dest)
    # inline, не attachment: attachment iOS-оверлей рендерит белым экраном.
    disposition = resp.headers.get("content-disposition", "")
    assert disposition.startswith("inline")
    assert "blank.xlsx" in disposition

    # Битая подпись — 403 до похода на диск.
    with pytest.raises(HTTPException) as exc:
        await serve_material_file(material.id, v=1, e=int(q["e"][0]), s="0" * 32)
    assert exc.value.status_code == 403

    # Выдача библиотеки несёт ГОТОВЫЙ подписанный адрес: iOS standalone
    # не скриптует окно после window.open('') — кнопке нужен href заранее.
    from app.api.library import get_library

    library = await get_library(False, member, db)
    mine = next(m for m in library.materials if m.id == material.id)
    assert mine.download_url is not None
    lp = urlparse(mine.download_url)
    lq = parse_qs(lp.query)
    served = await serve_material_file(
        material.id, v=int(lq["v"][0]), e=int(lq["e"][0]), s=lq["s"][0]
    )
    assert str(served.path) == str(dest)


# ─── Материал-ссылка и смена типа «Файл ↔ Ссылка» (02.09) ────────────────────


async def test_link_material_lifecycle_and_url_guard(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Link-путь целиком: публикация без файла, ознакомление v0, запреты.

    До 02.09 у link-пути не было ни одного бэкенд-теста; PATCH {"url": null}
    молча персистил ссылку без адреса (слепой setattr) — теперь 422."""
    import io

    from fastapi import HTTPException, UploadFile

    from app.api.library import (
        acknowledge,
        change_status,
        create_material,
        track_open,
        update_material,
        upload_version,
    )
    from app.schemas.library import AckBody, MaterialCreate, MaterialUpdate, StatusBody
    from tests.integration.test_courses import _mk_member

    publisher, pub_profile = await _mk_member(
        db, tenant_id, email=f"pub-{uuid.uuid4().hex[:6]}@t.ru"
    )
    pub_profile.content_role = "publisher"
    member, _member_profile = await _mk_member(
        db, tenant_id, email=f"m-{uuid.uuid4().hex[:6]}@t.ru"
    )
    await db.flush()

    created = await create_material(
        MaterialCreate(
            title="Облачная папка",
            kind="link",
            url="https://disk.example/x",
            requires_acknowledgement=True,
        ),
        publisher,
        db,
    )
    # Публикация ссылки не требует файла (гейт «Сначала загрузите файл» — про file).
    await change_status(created.id, StatusBody(status="published"), publisher, db)

    # Ознакомление: клик «Открыть ссылку» = /open, отметка — с version_no=0.
    await track_open(created.id, member, db)
    acked = await acknowledge(created.id, AckBody(version_no=0), member, db)
    assert acked.acked_by_me is True

    # Версий у ссылки нет.
    with pytest.raises(HTTPException) as exc:
        await upload_version(
            created.id,
            UploadFile(file=io.BytesIO(b"x"), filename="a.pdf"),
            publisher,
            db,
        )
    assert exc.value.status_code == 422

    # Дыра закрыта: ссылку нельзя оставить без адреса.
    with pytest.raises(HTTPException) as exc:
        await update_material(created.id, MaterialUpdate(url=None), publisher, db)
    assert exc.value.status_code == 422
    assert "URL" in exc.value.detail


async def test_material_kind_switch_file_link_file(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Смена типа: file→link снимает версию (ack-версия становится 0 —
    у re_ack-материалов повторное ознакомление), link→file восстанавливает
    последнюю загруженную версию."""
    from app.api.library import update_material
    from app.models.library import MaterialVersion
    from app.schemas.library import MaterialUpdate
    from tests.integration.test_courses import _mk_member

    publisher, pub_profile = await _mk_member(
        db, tenant_id, email=f"pub-{uuid.uuid4().hex[:6]}@t.ru"
    )
    pub_profile.content_role = "publisher"
    await db.flush()

    material = await _mk_material(
        db,
        tenant_id,
        title="Сменный тип",
        status="published",
        current_version_no=1,
        re_ack_on_new_version=True,
    )
    db.add(
        MaterialVersion(
            material_id=material.id,
            tenant_id=tenant_id,
            version_no=1,
            storage_key="lib/x",
            file_name="a.pdf",
            mime="application/pdf",
            size_bytes=10,
        )
    )
    await db.flush()

    resp = await update_material(
        material.id,
        MaterialUpdate(kind="link", url="https://disk.example/doc"),
        publisher,
        db,
    )
    assert resp.kind == "link" and resp.url == "https://disk.example/doc"
    await db.refresh(material)
    assert material.current_version_no is None
    assert _effective_ack_version(material) == 0

    resp = await update_material(material.id, MaterialUpdate(kind="file"), publisher, db)
    assert resp.kind == "file" and resp.url is None
    await db.refresh(material)
    assert material.current_version_no == 1


async def test_published_link_to_file_requires_version(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """У ОПУБЛИКОВАННОГО материала смена link→file без загруженных версий — 422
    (иначе жил бы опубликованный материал с download-404); черновику можно —
    файл догружается из карточки."""
    from fastapi import HTTPException

    from app.api.library import update_material
    from app.schemas.library import MaterialUpdate
    from tests.integration.test_courses import _mk_member

    publisher, pub_profile = await _mk_member(
        db, tenant_id, email=f"pub-{uuid.uuid4().hex[:6]}@t.ru"
    )
    pub_profile.content_role = "publisher"
    await db.flush()

    published = await _mk_material(
        db, tenant_id, title="Живая ссылка", kind="link",
        url="https://disk.example/a", status="published",
    )
    with pytest.raises(HTTPException) as exc:
        await update_material(published.id, MaterialUpdate(kind="file"), publisher, db)
    assert exc.value.status_code == 422
    assert "загрузите файл" in exc.value.detail

    draft = await _mk_material(
        db, tenant_id, title="Черновик-ссылка", kind="link", url="https://disk.example/b"
    )
    resp = await update_material(draft.id, MaterialUpdate(kind="file"), publisher, db)
    assert resp.kind == "file" and resp.url is None and resp.current_version_no is None


async def test_section_audience_closes_its_materials(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """ОС 25.08: аудиторию раздела наконец можно задать.

    Колонка и фильтр по ней жили в коде с Ф2, ручки не было — «раздел только
    для руководителей» приходилось собирать по одному материалу. Проверяем всю
    цепочку: ручка → материализация состава → выдача `/learn/library`.
    """
    from fastapi import HTTPException

    from app.api.library import get_library, set_section_audience
    from app.models.library import LibrarySection
    from app.schemas.library import AudienceBody
    from app.schemas.org import AudienceRuleBody
    from tests.integration.test_courses import _mk_member

    publisher, publisher_profile = await _mk_member(db, tenant_id, email="pub-sec@t.ru")
    publisher_profile.content_role = "publisher"
    inside_principal, insider = await _mk_member(db, tenant_id, email="in@t.ru")
    outside_principal, _outsider = await _mk_member(db, tenant_id, email="out@t.ru")
    await db.flush()

    section = LibrarySection(tenant_id=tenant_id, title="Только для своих")
    db.add(section)
    await db.flush()
    material = await _mk_material(
        db, tenant_id, title="Закрытый регламент", status="published", section_id=section.id
    )
    await db.commit()

    # Publisher обязателен: раздел — это доступ, а не оформление.
    with pytest.raises(HTTPException) as exc:
        await set_section_audience(
            section.id, AudienceBody(is_all=False, rules=[]), outside_principal, db
        )
    assert exc.value.status_code == 403

    await set_section_audience(
        section.id,
        AudienceBody(
            is_all=False,
            rules=[AudienceRuleBody(mode="include", profile_ids=[insider.id])],
        ),
        publisher,
        db,
    )
    await db.refresh(section)
    assert section.audience_id is not None

    inside = await get_library(False, inside_principal, db)
    assert section.id in [s.id for s in inside.sections]
    assert material.id in [m.id for m in inside.materials]

    outside = await get_library(False, outside_principal, db)
    assert section.id not in [s.id for s in outside.sections]
    # Материал опубликован и сам по себе открыт всем — прячет его именно раздел.
    assert material.id not in [m.id for m in outside.materials]

    # Возврат к «Всем» открывает обратно, без ручной чистки материалов.
    await set_section_audience(section.id, AudienceBody(is_all=True), publisher, db)
    await db.refresh(section)
    assert section.audience_id is None
    reopened = await get_library(False, outside_principal, db)
    assert material.id in [m.id for m in reopened.materials]

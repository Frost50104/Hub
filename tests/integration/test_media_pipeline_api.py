"""Конвейер видео (0066): гейты и админ-настройки.

Ручки зовутся напрямую (как везде в integration): 404 при выключенном env,
тумблер тенанта + аудит, валидация сцены гуся (картинка 16:9 своего тенанта).
"""

from __future__ import annotations

import struct
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api.media import get_media_admin_settings, put_media_admin_settings
from app.config import get_settings
from app.models.audit import AuditLog
from app.models.course import MediaFile
from app.schemas.media import MediaAdminSettingsPut
from app.services.media import gate
from tests.integration.conftest import make_principal
from tests.integration.test_project_access import _register

pytestmark = pytest.mark.integration


@pytest.fixture
def pipeline_env(monkeypatch, tmp_path):
    monkeypatch.setenv("SIGNARIS_HUB_MEDIA_PIPELINE_ENABLED", "true")
    monkeypatch.delenv("SIGNARIS_HUB_MEDIA_AVATAR_ENABLED", raising=False)
    get_settings.cache_clear()
    monkeypatch.setattr(get_settings(), "attachments_root", tmp_path)
    yield tmp_path
    get_settings.cache_clear()


def _png(w: int, h: int) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 13)
        + b"IHDR"
        + struct.pack(">II", w, h)
        + b"\x08\x06"
        + b"\x00" * 64
    )


async def _image(db, tenant_id, root, *, kind="image", mime="image/png", body=b"") -> MediaFile:
    media = MediaFile(
        tenant_id=tenant_id,
        kind=kind,
        storage_key=f"{tenant_id}/learn/media/{uuid.uuid4()}-scene.png",
        file_name="scene.png",
        mime=mime,
        size_bytes=len(body),
    )
    db.add(media)
    await db.flush()
    path = root / media.storage_key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return media


async def test_settings_are_404_when_env_flag_is_off(db, tenant_id, monkeypatch):
    monkeypatch.setenv("SIGNARIS_HUB_MEDIA_PIPELINE_ENABLED", "false")
    get_settings.cache_clear()
    admin = make_principal(tenant_id, role="admin")
    with pytest.raises(HTTPException) as exc:
        await get_media_admin_settings(admin, db)
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        await put_media_admin_settings(MediaAdminSettingsPut(enabled=True), admin, db)
    assert exc.value.status_code == 404
    get_settings.cache_clear()


async def test_tenant_toggle_roundtrip_writes_audit_once(rls_enforced, db, tenant_id, pipeline_env):
    admin = make_principal(tenant_id, role="admin", tenant_slug=f"media-{uuid.uuid4().hex[:8]}")
    await _register(db, admin)
    await db.commit()

    out = await get_media_admin_settings(admin, db)
    assert out.enabled is False and out.env_enabled is True
    assert out.stt_configured is False, "media_stt_url не задан — расшифровки нет"
    assert out.avatar_env_enabled is False
    assert out.month_used_minutes == 0 and out.active_jobs == 0
    assert await gate.pipeline_enabled_for(db, tenant_id) is False

    out = await put_media_admin_settings(
        MediaAdminSettingsPut(enabled=True, glossary="UPPETIT, iiko", avatar_resolution="540p"),
        admin,
        db,
    )
    assert out.enabled is True
    assert out.glossary == "UPPETIT, iiko" and out.avatar_resolution == "540p"
    assert await gate.pipeline_enabled_for(db, tenant_id) is True

    rows = (
        (await db.execute(select(AuditLog).where(AuditLog.object_type == "media_settings")))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].diff["enabled"] == {"old": False, "new": True}
    assert rows[0].diff["glossary"]["new"] == "UPPETIT, iiko"

    # Повтор тех же значений — без новой строки аудита.
    await put_media_admin_settings(MediaAdminSettingsPut(enabled=True), admin, db)
    rows = (
        (await db.execute(select(AuditLog).where(AuditLog.object_type == "media_settings")))
        .scalars()
        .all()
    )
    assert len(rows) == 1

    # Выключение возвращает гейт, настройки остаются.
    out = await put_media_admin_settings(MediaAdminSettingsPut(enabled=False), admin, db)
    assert out.enabled is False and out.glossary == "UPPETIT, iiko"
    assert await gate.pipeline_enabled_for(db, tenant_id) is False


async def test_scene_must_be_a_ready_16_9_image(rls_enforced, db, tenant_id, pipeline_env):
    admin = make_principal(tenant_id, role="admin", tenant_slug=f"media-{uuid.uuid4().hex[:8]}")
    await _register(db, admin)
    square = await _image(db, tenant_id, pipeline_env, body=_png(1024, 1024))
    wide = await _image(db, tenant_id, pipeline_env, body=_png(1920, 1080))
    video = await _image(db, tenant_id, pipeline_env, kind="video", mime="video/mp4")
    await db.commit()

    with pytest.raises(HTTPException) as exc:
        await put_media_admin_settings(MediaAdminSettingsPut(scene_media_id=square.id), admin, db)
    assert exc.value.status_code == 422 and "16:9" in exc.value.detail

    with pytest.raises(HTTPException) as exc:
        await put_media_admin_settings(MediaAdminSettingsPut(scene_media_id=video.id), admin, db)
    assert exc.value.status_code == 422

    with pytest.raises(HTTPException) as exc:
        await put_media_admin_settings(
            MediaAdminSettingsPut(scene_media_id=uuid.uuid4()), admin, db
        )
    assert exc.value.status_code == 422

    out = await put_media_admin_settings(MediaAdminSettingsPut(scene_media_id=wide.id), admin, db)
    assert out.scene_media_id == wide.id
    assert out.scene_url is not None and f"/api/media/{wide.id}" in out.scene_url

    out = await put_media_admin_settings(MediaAdminSettingsPut(scene_media_id=None), admin, db)
    assert out.scene_media_id is None and out.scene_url is None

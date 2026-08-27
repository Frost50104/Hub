"""Бейдж проекта: whitelist, магические байты, взаимоисключение, CHECK'и в БД.

Эти байты отдаются INLINE в `<img>`, поэтому проверки типа здесь строже, чем у
вложений: у вложения `Content-Disposition: attachment`, и подсунутый html
скачается, а не выполнится.
"""

from __future__ import annotations

import io
import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.projects import create_project, set_project_badge, upload_project_badge
from app.config import get_settings
from app.models.project import Project
from app.schemas.project import ProjectBadgeUpdate, ProjectCreate
from app.services.attachments import absolute_path
from app.services.project_badge import BADGE_MAX_BYTES
from tests.integration.conftest import make_principal
from tests.integration.test_project_access import _add_member, _register

pytestmark = pytest.mark.integration

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _upload(data: bytes, name: str, mime: str) -> UploadFile:
    return UploadFile(file=io.BytesIO(data), filename=name, headers={"content-type": mime})


@pytest.fixture
def storage(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(get_settings(), "attachments_root", tmp_path)
    return tmp_path


async def _seed(db: AsyncSession, tenant_id: uuid.UUID):
    slug = uuid.uuid4().hex[:6]
    owner = make_principal(
        tenant_id, email=f"own-{slug}@t.ru", role="member", tenant_slug=slug
    )
    await _register(db, owner, org_role="office")
    project = await create_project(ProjectCreate(name=f"Бейдж {slug}"), owner, db)
    await db.commit()
    return owner, project


async def test_upload_sets_image_and_clears_emoji(
    db: AsyncSession, tenant_id: uuid.UUID, storage: Path
):
    owner, project = await _seed(db, tenant_id)
    await set_project_badge(project.id, ProjectBadgeUpdate(emoji="🚀"), owner, db)

    resp = await upload_project_badge(
        project.id, file=_upload(PNG, "b.png", "image/png"), principal=owner, db=db
    )

    assert resp.badge_emoji is None
    assert resp.badge_url is not None and "?s=" in resp.badge_url
    row = await db.get(Project, project.id)
    assert row.badge_mime == "image/png"
    assert absolute_path(row.badge_storage_key).is_file()


async def test_emoji_clears_image_and_unlinks_blob(
    db: AsyncSession, tenant_id: uuid.UUID, storage: Path
):
    owner, project = await _seed(db, tenant_id)
    await upload_project_badge(
        project.id, file=_upload(PNG, "b.png", "image/png"), principal=owner, db=db
    )
    old = absolute_path((await db.get(Project, project.id)).badge_storage_key)

    resp = await set_project_badge(project.id, ProjectBadgeUpdate(emoji="🚀"), owner, db)

    assert resp.badge_emoji == "🚀"
    assert resp.badge_url is None
    assert not old.exists()


async def test_replace_changes_url_and_unlinks_old(
    db: AsyncSession, tenant_id: uuid.UUID, storage: Path
):
    """Версия адреса — сам storage_key, иначе браузер показывал бы старую."""
    owner, project = await _seed(db, tenant_id)
    first = await upload_project_badge(
        project.id, file=_upload(PNG, "a.png", "image/png"), principal=owner, db=db
    )
    old = absolute_path((await db.get(Project, project.id)).badge_storage_key)

    second = await upload_project_badge(
        project.id, file=_upload(PNG, "b.png", "image/png"), principal=owner, db=db
    )

    assert second.badge_url != first.badge_url
    assert not old.exists()


async def test_clear_badge_returns_to_letters(
    db: AsyncSession, tenant_id: uuid.UUID, storage: Path
):
    owner, project = await _seed(db, tenant_id)
    await upload_project_badge(
        project.id, file=_upload(PNG, "b.png", "image/png"), principal=owner, db=db
    )

    resp = await set_project_badge(project.id, ProjectBadgeUpdate(emoji=None), owner, db)

    assert resp.badge_emoji is None and resp.badge_url is None


async def test_rejects_mime_mismatch(
    db: AsyncSession, tenant_id: uuid.UUID, storage: Path
):
    """Регресс QA-0821 #11: `MZ…` под именем .png проходил."""
    owner, project = await _seed(db, tenant_id)
    with pytest.raises(HTTPException) as exc:
        await upload_project_badge(
            project.id,
            file=_upload(b"MZ\x90\x00" + b"\x00" * 64, "b.png", "image/png"),
            principal=owner,
            db=db,
        )
    assert exc.value.status_code == 415


@pytest.mark.parametrize(
    ("name", "mime"),
    [("i.svg", "image/svg+xml"), ("i.gif", "image/gif"), ("i.heic", "image/heic")],
)
async def test_rejects_types_outside_whitelist(
    db: AsyncSession, tenant_id: uuid.UUID, storage: Path, name: str, mime: str
):
    owner, project = await _seed(db, tenant_id)
    with pytest.raises(HTTPException) as exc:
        await upload_project_badge(
            project.id, file=_upload(PNG, name, mime), principal=owner, db=db
        )
    assert exc.value.status_code == 415


async def test_rejects_oversize_and_leaves_no_file(
    db: AsyncSession, tenant_id: uuid.UUID, storage: Path
):
    owner, project = await _seed(db, tenant_id)
    big = PNG + b"\x00" * (BADGE_MAX_BYTES + 1)
    with pytest.raises(HTTPException) as exc:
        await upload_project_badge(
            project.id, file=_upload(big, "b.png", "image/png"), principal=owner, db=db
        )
    assert exc.value.status_code == 413
    assert list(storage.rglob("*.png")) == []


async def _member(db: AsyncSession, tenant_id: uuid.UUID, project_id: uuid.UUID, role: str):
    slug = uuid.uuid4().hex[:6]
    principal = make_principal(
        tenant_id, email=f"{role}-{slug}@t.ru", tenant_slug=f"{role}{slug}"
    )
    await _register(db, principal)
    await _add_member(db, tenant_id, project_id, principal, role)
    return principal


async def test_editor_can_set_badge(db: AsyncSession, tenant_id: uuid.UUID):
    """Бейдж — профиль проекта, а не управление им: гейт edit-tier.

    До 27.08 здесь стоял 403: ручка требовала владельца, и редактор не мог
    поставить значок проекту, задачи в котором он ведёт.
    """
    _owner, project = await _seed(db, tenant_id)
    editor = await _member(db, tenant_id, project.id, "editor")

    resp = await set_project_badge(project.id, ProjectBadgeUpdate(emoji="🚀"), editor, db)
    assert resp.badge_emoji == "🚀"


async def test_editor_can_upload_badge_image(
    db: AsyncSession, tenant_id: uuid.UUID, storage: Path
):
    """Multipart-путь гейтится отдельно от эмодзи — проверяем и его."""
    _owner, project = await _seed(db, tenant_id)
    editor = await _member(db, tenant_id, project.id, "editor")

    resp = await upload_project_badge(
        project.id, file=_upload(PNG, "b.png", "image/png"), principal=editor, db=db
    )
    assert resp.badge_url is not None


async def test_viewer_cannot_set_badge(db: AsyncSession, tenant_id: uuid.UUID):
    """Граница, которая не должна съехать вместе с послаблением."""
    _owner, project = await _seed(db, tenant_id)
    viewer = await _member(db, tenant_id, project.id, "viewer")

    with pytest.raises(HTTPException) as exc:
        await set_project_badge(project.id, ProjectBadgeUpdate(emoji="🚀"), viewer, db)
    assert exc.value.status_code == 403


async def test_personal_project_badge_allowed(db: AsyncSession, tenant_id: uuid.UUID):
    """Симметрия с переименованием: скрытость держит колонка, а не значок."""
    from app.services.personal_projects import ensure_personal_project

    slug = uuid.uuid4().hex[:6]
    owner = make_principal(tenant_id, email=f"p-{slug}@t.ru", tenant_slug=f"p{slug}")
    await _register(db, owner)
    personal_id = await ensure_personal_project(db, owner)
    await db.commit()

    resp = await set_project_badge(personal_id, ProjectBadgeUpdate(emoji="🏠"), owner, db)
    assert resp.badge_emoji == "🏠"


async def test_db_check_blocks_both_sources(db: AsyncSession, tenant_id: uuid.UUID):
    """CHECK обязан жить в БД, а не только в коде."""
    _owner, project = await _seed(db, tenant_id)
    with pytest.raises(IntegrityError):
        await db.execute(
            text(
                "UPDATE projects SET badge_emoji = '🚀', "
                "badge_storage_key = 'x', badge_mime = 'image/png' WHERE id = :i"
            ),
            {"i": project.id},
        )
    await db.rollback()


async def test_db_check_blocks_html_mime(db: AsyncSession, tenant_id: uuid.UUID):
    """Этот mime уходит в Content-Type отдаваемых inline байт."""
    _owner, project = await _seed(db, tenant_id)
    with pytest.raises(IntegrityError):
        await db.execute(
            text(
                "UPDATE projects SET badge_storage_key = 'x', "
                "badge_mime = 'text/html' WHERE id = :i"
            ),
            {"i": project.id},
        )
    await db.rollback()


async def test_db_check_blocks_orphan_mime(db: AsyncSession, tenant_id: uuid.UUID):
    """Блоб и его тип живут и умирают вместе."""
    _owner, project = await _seed(db, tenant_id)
    with pytest.raises(IntegrityError):
        await db.execute(
            text("UPDATE projects SET badge_mime = 'image/png' WHERE id = :i"),
            {"i": project.id},
        )
    await db.rollback()

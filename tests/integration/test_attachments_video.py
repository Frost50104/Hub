"""Видео во вложениях задачи (ОС 15.09).

Сотрудник не смог приложить к задаче видео. Рубежей, которые его не пускали,
было пять — клиентский список расширений, клиентский лимит 20 МБ, серверный
whitelist, серверный лимит и `client_max_body_size` в nginx. Здесь проверяются
серверные: whitelist с сигнатурами, собственный потолок размера у видео и
отдача по подписи, без которой файл нельзя показать в `<video>` (тег не шлёт
`Authorization`).

Лимиты в тестах занижены monkeypatch'ем: смысл проверки в том, что у видео
потолок ОТДЕЛЬНЫЙ, а не в том, чтобы записать на диск гигабайт.
"""

from __future__ import annotations

import io
import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.attachments import serve_attachment, upload_attachment
from app.api.projects import create_project
from app.api.tasks import create_task
from app.config import get_settings
from app.schemas.project import ProjectCreate
from app.schemas.task import TaskCreate
from app.services.learn_media import issue_token
from tests.integration.conftest import make_principal
from tests.integration.test_project_access import _register

pytestmark = pytest.mark.integration

# ISO-BMFF: размер бокса (4 байта) + 'ftyp' с 4-го. Ровно это и сниффит сервер.
MP4_HEAD = b"\x00\x00\x00\x20ftypisom\x00\x00\x02\x00"
PNG_HEAD = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8


def _upload(data: bytes, name: str, mime: str | None) -> UploadFile:
    """`size=` обязателен: настоящий парсер multipart его заполняет, и гейт
    свободного места на него опирается. Без него тест проверял бы не то, что
    работает в проде."""
    headers = {"content-type": mime} if mime else {}
    return UploadFile(
        file=io.BytesIO(data), size=len(data), filename=name, headers=headers
    )


@pytest.fixture
def storage(tmp_path: Path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "attachments_root", tmp_path)
    # Занижаем оба потолка: важно их РАЗЛИЧИЕ, а не абсолютные числа.
    monkeypatch.setattr(settings, "attachment_max_bytes", 1_000)
    monkeypatch.setattr(settings, "attachment_video_max_bytes", 50_000)
    # X-Accel проверяем отдельным тестом; по умолчанию — как в проде.
    monkeypatch.setattr(settings, "media_accel_enabled", True)
    return tmp_path


async def _seed(db: AsyncSession, tenant_id: uuid.UUID, slug: str):
    owner = make_principal(tenant_id, email=f"{slug}@t.ru", tenant_slug=slug)
    await _register(db, owner, org_role="office")
    project = await create_project(ProjectCreate(name=f"Проект {slug}"), owner, db)
    task = await create_task(project.id, TaskCreate(title="Снять видео"), owner, db)
    await db.commit()
    return owner, task


async def test_mp4_is_accepted_and_gets_a_player_url(db, tenant_id, storage):
    owner, task = await _seed(db, tenant_id, "vid-ok")

    out = await upload_attachment(
        task_id=task.id,
        file=_upload(MP4_HEAD + b"\x00" * 4_000, "VID_20260915.mp4", "video/mp4"),
        principal=owner,
        db=db,
    )

    assert out.mime == "video/mp4"
    assert out.filename == "VID_20260915.mp4"
    # Адрес для <video> — только у видео, и он ведёт на ручку отдачи.
    assert out.preview_url is not None
    assert out.preview_url.startswith(f"/api/attachments/{out.id}/file?e=")


async def test_documents_do_not_get_a_player_url(db, tenant_id, storage):
    owner, task = await _seed(db, tenant_id, "vid-doc")

    out = await upload_attachment(
        task_id=task.id,
        file=_upload(PNG_HEAD, "схема.png", "image/png"),
        principal=owner,
        db=db,
    )

    # Inline-показ image/* — отдельная задача (и HEIC/HEIF из неё придётся
    # исключать), поэтому картинке адрес не выдаётся.
    assert out.preview_url is None


async def test_video_ceiling_is_separate_from_the_document_one(db, tenant_id, storage):
    """Главное свойство правки: 20 МБ документам, гигабайт видео.

    Файл одного и того же размера обязан пройти как видео и не пройти как
    документ — иначе «отдельный потолок» существует только на словах.
    """
    owner, task = await _seed(db, tenant_id, "vid-limit")
    payload = b"\x00" * 4_000

    ok = await upload_attachment(
        task_id=task.id,
        file=_upload(MP4_HEAD + payload, "clip.mp4", "video/mp4"),
        principal=owner,
        db=db,
    )
    assert ok.size_bytes == len(MP4_HEAD) + 4_000

    with pytest.raises(HTTPException) as err:
        await upload_attachment(
            task_id=task.id,
            file=_upload(PNG_HEAD + payload, "снимок.png", "image/png"),
            principal=owner,
            db=db,
        )
    assert err.value.status_code == 413


async def test_video_over_its_own_ceiling_is_rejected(db, tenant_id, storage):
    owner, task = await _seed(db, tenant_id, "vid-big")

    with pytest.raises(HTTPException) as err:
        await upload_attachment(
            task_id=task.id,
            file=_upload(MP4_HEAD + b"\x00" * 60_000, "long.mp4", "video/mp4"),
            principal=owner,
            db=db,
        )
    assert err.value.status_code == 413


async def test_octet_stream_video_is_recovered(db, tenant_id, storage):
    """Файловые менеджеры Android шлют видео как octet-stream.

    Без восстановления MIME из расширения правка чинила бы задачу наполовину:
    whitelist пропустил бы только те загрузки, где браузер угадал тип.
    """
    owner, task = await _seed(db, tenant_id, "vid-octet")

    out = await upload_attachment(
        task_id=task.id,
        file=_upload(MP4_HEAD + b"\x00" * 100, "IMG_0042.MOV", "application/octet-stream"),
        principal=owner,
        db=db,
    )
    assert out.mime == "video/quicktime"


async def test_renamed_executable_is_rejected(db, tenant_id, storage):
    """Whitelist обходится переименованием — держит сигнатура."""
    owner, task = await _seed(db, tenant_id, "vid-fake")

    with pytest.raises(HTTPException) as err:
        await upload_attachment(
            task_id=task.id,
            file=_upload(b"MZ\x90\x00\x03\x00\x00\x00" * 8, "setup.mp4", "video/mp4"),
            principal=owner,
            db=db,
        )
    assert err.value.status_code == 415
    assert "не соответствует" in err.value.detail


async def test_low_disk_blocks_upload(monkeypatch, storage):
    """Диск общий с Postgres — загрузка не должна его добивать.

    Гейта у вложений не было вовсе (он стоял только у медиа уроков и бейджей);
    с файлами по гигабайту это перестало быть терпимым.
    """
    import app.api.attachments as mod

    settings = get_settings()
    monkeypatch.setattr(settings, "media_min_free_bytes", 5_000_000_000)
    monkeypatch.setattr(mod, "check_free_space", lambda: 5_000_000_100)

    # Запас нужен ровно на ОДНУ копию: спул Starlette уже лежит на диске, и
    # `check_free_space` его учитывает. 200 байт поверх 100 свободных — отказ.
    file = _upload(MP4_HEAD + b"\x00" * 200, "clip.mp4", "video/mp4")
    with pytest.raises(HTTPException) as err:
        mod._assert_free_space(file)
    assert err.value.status_code == 507

    # А маленький файл при тех же свободных байтах проходит: скриншот не обязан
    # требовать гигабайта.
    mod._assert_free_space(_upload(PNG_HEAD, "a.png", "image/png"))


async def test_serving_requires_a_valid_signature(db, tenant_id, storage):
    owner, task = await _seed(db, tenant_id, "vid-sign")
    out = await upload_attachment(
        task_id=task.id,
        file=_upload(MP4_HEAD + b"\x00" * 100, "clip.mp4", "video/mp4"),
        principal=owner,
        db=db,
    )
    exp, sig = issue_token(f"attach:{out.id}", get_settings().media_url_ttl_sec)

    resp = await serve_attachment(attachment_id=out.id, e=exp, s=sig)
    assert resp.status_code == 200
    # Range/206 отдаёт nginx по internal-локации, Python не стримит.
    assert resp.headers["X-Accel-Redirect"].startswith("/_protected_media/")
    assert resp.headers["Content-Type"] == "video/mp4"
    assert resp.headers["Content-Disposition"].startswith("inline")

    with pytest.raises(HTTPException) as err:
        await serve_attachment(attachment_id=out.id, e=exp, s="0" * 32)
    assert err.value.status_code == 403


async def test_signature_of_one_attachment_does_not_open_another(db, tenant_id, storage):
    owner, task = await _seed(db, tenant_id, "vid-cross")
    mine = await upload_attachment(
        task_id=task.id,
        file=_upload(MP4_HEAD + b"\x00" * 100, "mine.mp4", "video/mp4"),
        principal=owner,
        db=db,
    )
    foreign = await upload_attachment(
        task_id=task.id,
        file=_upload(MP4_HEAD + b"\x00" * 100, "foreign.mp4", "video/mp4"),
        principal=owner,
        db=db,
    )
    exp, sig = issue_token(f"attach:{mine.id}", get_settings().media_url_ttl_sec)

    with pytest.raises(HTTPException) as err:
        await serve_attachment(attachment_id=foreign.id, e=exp, s=sig)
    assert err.value.status_code == 403


async def test_dl_flag_switches_to_download(db, tenant_id, storage):
    """Та же ссылка, но «сохранить»: гигабайт нельзя тянуть блобом в память."""
    owner, task = await _seed(db, tenant_id, "vid-dl")
    out = await upload_attachment(
        task_id=task.id,
        file=_upload(MP4_HEAD + b"\x00" * 100, "clip.mp4", "video/mp4"),
        principal=owner,
        db=db,
    )
    exp, sig = issue_token(f"attach:{out.id}", get_settings().media_url_ttl_sec)

    resp = await serve_attachment(attachment_id=out.id, e=exp, s=sig, dl=1)
    assert resp.headers["Content-Disposition"].startswith("attachment")


async def test_legacy_upload_route_still_works(db, tenant_id, storage):
    """Вчерашний бандл грузит на прежний адрес — он обязан работать.

    PWA обновляется неделями (`registerType: 'prompt'`).
    """
    from app.api.attachments import upload_attachment_legacy

    owner, task = await _seed(db, tenant_id, "vid-legacy")
    out = await upload_attachment_legacy(
        task_id=task.id,
        file=_upload(PNG_HEAD, "старый.png", "image/png"),
        principal=owner,
        db=db,
    )
    assert out.filename == "старый.png"

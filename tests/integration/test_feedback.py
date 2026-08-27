"""Обратная связь из настроек → задача в проекте развития.

Форма открыта каждому сотруднику и пишет в проект, участником которого он не
является. Проверяем именно то, что из этого следует: задача доходит, владелец
узнаёт, а отправитель не получает ни доступа, ни подписки на чужую задачу.
"""

from __future__ import annotations

import io
import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.feedback import send_feedback
from app.api.projects import create_project
from app.config import get_settings
from app.models.attachment import TaskAttachment
from app.models.notification import Notification
from app.models.task import Task, TaskAssignee, TaskLabel, TaskLabelAssignment, TaskWatcher
from app.schemas.project import ProjectCreate
from app.services.feedback import FEEDBACK_LABEL, feedback_title
from tests.integration.conftest import make_principal, seed_stages
from tests.integration.test_project_access import _register

pytestmark = pytest.mark.integration

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _request(user_agent: str = "QA-Browser/1.0") -> Request:
    """Голый ASGI-scope: ручке нужен только заголовок устройства."""
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/feedback",
            "headers": [(b"user-agent", user_agent.encode())],
        }
    )


def _upload(data: bytes, name: str, mime: str) -> UploadFile:
    return UploadFile(file=io.BytesIO(data), filename=name, headers={"content-type": mime})


@pytest.fixture
def storage(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(get_settings(), "attachments_root", tmp_path)
    return tmp_path


async def _seed(db: AsyncSession, tenant_id: uuid.UUID, slug: str):
    """Проект приёма (ключ из настроек) + посторонний сотрудник-отправитель."""
    owner = make_principal(
        tenant_id, email=f"owner-{slug}@t.ru", role="member", tenant_slug=slug
    )
    await _register(db, owner, org_role="office")
    project = await create_project(
        ProjectCreate(name="Развитие Hub", key=get_settings().feedback_project_key),
        owner,
        db,
    )
    await seed_stages(db, project.id, owner, names=("Входящие", "В работе"))

    sender = make_principal(tenant_id, email=f"sender-{slug}@t.ru", tenant_slug=slug)
    await _register(db, sender)
    await db.commit()
    return owner, project, sender


async def test_feedback_lands_in_first_column_with_label_and_owner(
    db: AsyncSession, tenant_id: uuid.UUID
):
    owner, project, sender = await _seed(db, tenant_id, "snd1")

    await send_feedback(
        _request(),
        text="Кнопка «Готово» не нажимается\nВторая строка с деталями",
        files=None,
        file=None,
        principal=sender,
        db=db,
    )

    task = (
        await db.execute(select(Task).where(Task.project_id == project.id))
    ).scalar_one()
    assert task.title == "Кнопка «Готово» не нажимается"
    # Первая колонка проекта — «Входящие».
    stages = await db.execute(
        select(Task.stage_id).where(Task.id == task.id)
    )
    assert stages.scalar_one() is not None
    # Автор виден в задаче и назван в описании — иначе не к кому вернуться.
    assert task.created_by == sender.employee_id
    assert sender.email in (task.description or "")
    assert "Версия Hub" in (task.description or "")

    labels = (
        await db.execute(
            select(TaskLabel.name)
            .join(TaskLabelAssignment, TaskLabelAssignment.label_id == TaskLabel.id)
            .where(TaskLabelAssignment.task_id == task.id)
        )
    ).scalars().all()
    assert list(labels) == [FEEDBACK_LABEL]

    assignees = (
        await db.execute(
            select(TaskAssignee.employee_id).where(TaskAssignee.task_id == task.id)
        )
    ).scalars().all()
    assert list(assignees) == [owner.employee_id]


async def test_owner_is_notified_but_sender_is_not_subscribed(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Владелец узнаёт, отправитель — не наблюдатель чужой задачи.

    Подписка автора (`create_task_record` делает её всем) привела бы его по
    пушу в проект, которого он не видит, то есть в 403.
    """
    owner, project, sender = await _seed(db, tenant_id, "snd2")
    await send_feedback(
        _request(), text="Тормозит поиск", files=None, file=None, principal=sender, db=db
    )

    task = (
        await db.execute(select(Task).where(Task.project_id == project.id))
    ).scalar_one()
    watchers = (
        await db.execute(
            select(TaskWatcher.employee_id).where(TaskWatcher.task_id == task.id)
        )
    ).scalars().all()
    assert sender.employee_id not in watchers
    assert owner.employee_id in watchers  # подписан как исполнитель

    kinds = (
        await db.execute(
            select(Notification.kind, Notification.employee_id).where(
                Notification.employee_id == owner.employee_id
            )
        )
    ).all()
    assert ("task.assigned_to_me", owner.employee_id) in kinds


async def test_several_files_land_on_one_task(
    db: AsyncSession, tenant_id: uuid.UUID, storage: Path
):
    """Файлов может быть много: одному багу нужна серия скриншотов."""
    _owner, project, sender = await _seed(db, tenant_id, "snd8")
    await send_feedback(
        _request(),
        text="Три шага до ошибки",
        files=[
            _upload(PNG, "step1.png", "image/png"),
            _upload(PNG, "step2.png", "image/png"),
            _upload(b"%PDF-1.4 log", "log.pdf", "application/pdf"),
        ],
        file=None,
        principal=sender,
        db=db,
    )

    task = (
        await db.execute(select(Task).where(Task.project_id == project.id))
    ).scalar_one()
    rows = (
        await db.execute(
            select(TaskAttachment).where(TaskAttachment.task_id == task.id)
        )
    ).scalars().all()
    assert sorted(r.filename for r in rows) == ["log.pdf", "step1.png", "step2.png"]
    for row in rows:
        assert (storage / row.storage_key).exists()


async def test_legacy_single_field_still_works(
    db: AsyncSession, tenant_id: uuid.UUID, storage: Path
):
    """Вчерашний бандл шлёт `file`, а не `files`.

    PWA живёт закешированной версией до применения обновления: отправка со
    старого клиента не должна падать 422 из-за переименованного поля.
    """
    _owner, project, sender = await _seed(db, tenant_id, "snd9")
    await send_feedback(
        _request(),
        text="Со старого клиента",
        files=None,
        file=_upload(PNG, "old.png", "image/png"),
        principal=sender,
        db=db,
    )
    task = (
        await db.execute(select(Task).where(Task.project_id == project.id))
    ).scalar_one()
    row = (
        await db.execute(
            select(TaskAttachment).where(TaskAttachment.task_id == task.id)
        )
    ).scalar_one()
    assert row.filename == "old.png"


async def test_too_many_files_are_refused_before_anything_is_written(
    db: AsyncSession, tenant_id: uuid.UUID, storage: Path
):
    """Потолок количества — единственная защита сверх rate-limit 5/час."""
    from app.api.feedback import MAX_FILES

    _owner, project, sender = await _seed(db, tenant_id, "snd10")
    with pytest.raises(HTTPException) as exc:
        await send_feedback(
            _request(),
            text="Много файлов",
            files=[
                _upload(PNG, f"s{i}.png", "image/png") for i in range(MAX_FILES + 1)
            ],
            file=None,
            principal=sender,
            db=db,
        )
    assert exc.value.status_code == 422
    # Ни задачи, ни байтов: проверка стоит ДО создания.
    assert (
        await db.execute(select(Task).where(Task.project_id == project.id))
    ).first() is None
    assert not list(storage.rglob("*.png"))


async def test_bad_file_in_the_middle_leaves_no_orphan_blobs(
    db: AsyncSession, tenant_id: uuid.UUID, storage: Path
):
    """Второй файл падает — первый не должен остаться на диске.

    Транзакция откатится и строк не будет, а снять записанные байты станет
    некому: sweeper'а в Hub нет.
    """
    _owner, _project, sender = await _seed(db, tenant_id, "snd11")
    with pytest.raises(HTTPException) as exc:
        await send_feedback(
            _request(),
            text="Первый хороший, второй поддельный",
            files=[
                _upload(PNG, "good.png", "image/png"),
                _upload(b"<html>hi</html>", "evil.png", "image/png"),
            ],
            file=None,
            principal=sender,
            db=db,
        )
    assert exc.value.status_code == 415
    await db.rollback()
    assert not list(storage.rglob("*.png"))


async def test_attachment_is_stored_and_linked(
    db: AsyncSession, tenant_id: uuid.UUID, storage: Path
):
    _owner, project, sender = await _seed(db, tenant_id, "snd3")
    await send_feedback(
        _request(),
        text="Скриншот прилагаю",
        files=[_upload(PNG, "screen.png", "image/png")],
        file=None,
        principal=sender,
        db=db,
    )

    task = (
        await db.execute(select(Task).where(Task.project_id == project.id))
    ).scalar_one()
    attachment = (
        await db.execute(
            select(TaskAttachment).where(TaskAttachment.task_id == task.id)
        )
    ).scalar_one()
    assert attachment.mime == "image/png"
    assert (storage / attachment.storage_key).exists()


async def test_disguised_file_is_refused(
    db: AsyncSession, tenant_id: uuid.UUID, storage: Path
):
    """Проверки те же, что у вложений задачи: html под видом png не проходит."""
    _owner, _project, sender = await _seed(db, tenant_id, "snd4")
    with pytest.raises(HTTPException) as exc:
        await send_feedback(
            _request(),
            text="Вот файл",
            files=[_upload(b"<html>hi</html>", "evil.png", "image/png")],
            file=None,
            principal=sender,
            db=db,
        )
    assert exc.value.status_code == 415


async def test_empty_text_is_rejected(db: AsyncSession, tenant_id: uuid.UUID):
    _owner, project, sender = await _seed(db, tenant_id, "snd5")
    with pytest.raises(HTTPException) as exc:
        await send_feedback(
            _request(), text="   \n  ", files=None, file=None, principal=sender, db=db
        )
    assert exc.value.status_code == 422
    assert (
        await db.execute(select(Task).where(Task.project_id == project.id))
    ).first() is None


async def test_missing_project_answers_503_not_500(
    db: AsyncSession, tenant_id: uuid.UUID, monkeypatch
):
    """Ключ проекта могли сменить или проект удалить — отправитель ни при чём."""
    _owner, _project, sender = await _seed(db, tenant_id, "snd6")
    monkeypatch.setattr(get_settings(), "feedback_project_key", "NOSUCHKEY")
    with pytest.raises(HTTPException) as exc:
        await send_feedback(
            _request(), text="Что-то важное", files=None, file=None, principal=sender, db=db
        )
    assert exc.value.status_code == 503


def test_feedback_title_cuts_by_word():
    long = "Очень длинное сообщение про то, как именно ломается кнопка " * 5
    title = feedback_title(long)
    assert len(title) <= 120
    assert title.endswith("…")
    # Обрыв по границе слова: полуслова в списке читаются как сбой рендера.
    assert not title[:-1].endswith(" ")


def test_feedback_title_takes_first_line():
    assert feedback_title("\n\nПервая строка\nвторая") == "Первая строка"


async def test_regular_task_still_subscribes_its_author(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Страховка на дефолт `watch_creator=True`.

    Обратная связь просит НЕ подписывать автора; если этот флаг однажды
    станет дефолтом, обычные задачи молча перестанут уведомлять создателя.
    """
    from app.api.tasks import create_task
    from app.schemas.task import TaskCreate

    owner, project, _sender = await _seed(db, tenant_id, "snd7")
    task = await create_task(project.id, TaskCreate(title="Обычная"), owner, db)
    await db.commit()

    watchers = (
        await db.execute(
            select(TaskWatcher.employee_id).where(TaskWatcher.task_id == task.id)
        )
    ).scalars().all()
    assert owner.employee_id in watchers

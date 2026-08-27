"""Проход 1 переноса из WEEEK: инварианты, которые импортёр держит сам.

Импортёр сознательно идёт мимо `create_task_record` (он обязан завести
creator-watcher'а и поставить `completed_at = now()`), а значит девять его
проверок переехали в джобу. Каждая из них — тест здесь: это не «покрытие»,
а контракт ревью для обхода сервиса.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.jobs.import_weeek_bundle import Importer
from app.jobs.weeek_common import KIND_PROJECT, KIND_TASK, hub_id
from app.models.attachment import TaskAttachment
from app.models.custom_field import CustomFieldDefinition, TaskCustomFieldValue
from app.models.notification import Notification
from app.models.project import Project, ProjectMember
from app.models.project_folder import ProjectFolder
from app.models.stage import ProjectStage
from app.models.task import Task, TaskAssignee, TaskWatcher
from tests.integration.conftest import make_principal
from tests.integration.test_project_access import _register

pytestmark = pytest.mark.integration

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _task(weeek_id: int, seq: int, **over) -> dict:
    row = {
        "weeek_id": weeek_id,
        "seq": seq,
        "position": seq,
        "title": f"Задача {weeek_id}",
        "body_md": "Тело",
        "priority": "medium",
        "done": False,
        "created_at": "2023-05-01T10:00:00+00:00",
        "updated_at": "2023-06-01T10:00:00+00:00",
        "completed_at": None,
        "due_day": None,
        "start_day": None,
        "stage_key": "к работе",
        "section_board_id": None,
        "parent_weeek_id": None,
        "parent_ref": None,
        "author_email": None,
        "assignees": [],
        "custom_values": [],
        "attachments": [],
        "attachment_names_only": [],
    }
    row.update(over)
    return row


def write_bundle(root: Path, *, known_email: str, unknown_email: str) -> Path:
    """Мини-бандл: два проекта и все интересные крайние случаи.

    `unknown_email` обязан быть УНИКАЛЬНЫМ на тест: контейнер работает под
    superuser, а он обходит RLS, поэтому `load_people` в джобе видит
    `shadow_users` всех тенантов сразу. Общий адрес «нет@в.hub» означал бы,
    что тест, зарегистрировавший его раньше, ломает соседние.
    """
    bundle = root / "weeek-bundle"
    (bundle / "projects").mkdir(parents=True)
    (bundle / "files").mkdir()
    (bundle / "files" / "att-1").write_bytes(PNG)

    project_a = {
        "weeek_id": 1,
        "name": "Подбор персонала",
        "key_hint": "PP",
        "description": "Описание",
        "folder_key": "19",
        "tasks_file": "projects/1.json",
        "task_count": 4,
        "max_seq": 4,
        "stages": [
            {"key": "к работе", "name": "К работе", "position": 0},
            {"key": "готово", "name": "Готово", "position": 1},
        ],
        "sections": [
            {"weeek_board_id": 11, "name": "Алена", "position": 0},
            {"weeek_board_id": 12, "name": "Юля", "position": 1},
        ],
        "custom_fields": [
            {"weeek_id": "cf-1", "name": "Контрагент", "type": "text",
             "options": [], "position": 1}
        ],
        "team_emails": [known_email],
    }
    project_b = {
        "weeek_id": 2,
        "name": "Дизайн",
        "key_hint": "DIZAYN",
        "description": None,
        "folder_key": None,
        "tasks_file": "projects/2.json",
        "task_count": 2,
        "max_seq": 2,
        "stages": [{"key": "к работе", "name": "К работе", "position": 0}],
        "sections": [],
        "custom_fields": [],
        "team_emails": [],
    }
    (bundle / "manifest.json").write_text(
        json.dumps(
            {
                "version": 1,
                "source": "weeek",
                "stats": {},
                "folders": [{"weeek_id": "19", "name": "Отдел Персонала", "position": 0}],
                "projects": [project_a, project_b],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (bundle / "projects/1.json").write_text(
        json.dumps(
            {
                "weeek_project_id": 1,
                "tasks": [
                    _task(
                        101, 1,
                        section_board_id=11,
                        assignees=[{"email": known_email, "name": "Свой"}],
                        custom_values=[{"field": "cf-1", "value": "ООО Ромашка"}],
                        attachments=[{
                            "weeek_id": "att-1", "file": "files/att-1", "name": "счёт.png",
                            "mime": "image/png", "size": len(PNG), "creator_email": None,
                        }],
                    ),
                    _task(
                        102, 2, parent_weeek_id=101, done=True,
                        completed_at="2023-07-01T08:00:00+00:00",
                        stage_key="готово", priority="urgent",
                        assignees=[{"email": known_email, "name": "Свой"}],
                        due_day="2023-06-30",
                    ),
                    _task(
                        103, 3, stage_key=None,
                        # Тот же файл WEEEK, что у задачи 101: в WEEEK один
                        # файл может висеть на нескольких задачах.
                        attachments=[{
                            "weeek_id": "att-1", "file": "files/att-1", "name": "счёт.png",
                            "mime": "image/png", "size": len(PNG), "creator_email": None,
                        }],
                    ),
                    _task(
                        104, 4,
                        assignees=[{"email": unknown_email, "name": "Андрей Доценко"}],
                        attachment_names_only=["видео.mov"],
                    ),
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (bundle / "projects/2.json").write_text(
        json.dumps(
            {
                "weeek_project_id": 2,
                "tasks": [
                    _task(201, 1, parent_ref={
                        "kind": "cross_project", "weeek_id": 101,
                        "title": "Задача 101", "project_weeek_id": 1}),
                    _task(202, 2, parent_ref={
                        "kind": "orphan", "weeek_id": 777,
                        "title": "Потерянная", "project_weeek_id": None}),
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return bundle


@pytest.fixture
def attachments_root(tmp_path: Path, monkeypatch):
    from app.config import get_settings

    root = tmp_path / "attachments"
    root.mkdir()
    monkeypatch.setenv("SIGNARIS_HUB_ATTACHMENTS_ROOT", str(root))
    get_settings.cache_clear()
    yield root
    get_settings.cache_clear()


async def _count(db: AsyncSession, model, tenant_id: uuid.UUID) -> int:
    """Счётчик В ПРЕДЕЛАХ тенанта.

    Контейнер тестов работает под superuser, а он обходит RLS безусловно
    (`tests/integration/conftest.py`) — без явного фильтра сюда попадали бы
    строки соседних тестов.
    """
    return (
        await db.execute(
            select(func.count()).select_from(model).where(model.tenant_id == tenant_id)
        )
    ).scalar_one()


async def _run(
    db: AsyncSession, tenant_id: uuid.UUID, bundle: Path, actor_id: uuid.UUID, *, apply=True
) -> Importer:
    importer = Importer(bundle, tenant_id=tenant_id, actor_id=actor_id, apply=apply)
    await importer.run(db)
    return importer


@pytest.fixture
async def imported(db: AsyncSession, tenant_id: uuid.UUID, tmp_path: Path, attachments_root):
    slug = f"weeek-{uuid.uuid4().hex[:8]}"
    actor = make_principal(tenant_id, email=f"actor-{slug}@t.ru", tenant_slug=slug)
    mate = make_principal(tenant_id, email=f"mate-{slug}@t.ru", tenant_slug=slug)
    await _register(db, actor, org_role="office")
    await _register(db, mate)
    await db.commit()
    unknown_email = f"unknown-{slug}@t.ru"
    bundle = write_bundle(tmp_path, known_email=mate.email, unknown_email=unknown_email)
    importer = await _run(db, tenant_id, bundle, actor.employee_id)
    return {
        "bundle": bundle, "actor": actor, "mate": mate,
        "importer": importer, "unknown_email": unknown_email,
    }


class TestStructure:
    async def test_projects_stages_and_folder(self, db: AsyncSession, imported):
        tenant = imported["actor"].tenant_id
        projects = (
            await db.execute(
                select(Project).where(Project.tenant_id == tenant).order_by(Project.key)
            )
        ).scalars().all()
        assert len(projects) == 2
        # Ключ подбирает джоба по занятым в тенанте, поэтому проверяем ОСНОВУ,
        # а не точное значение: «PP» и «PP2» одинаково валидны.
        assert sorted(p.key.rstrip("0123456789") for p in projects) == ["DIZAYN", "PP"]

        pp = await db.get(Project, hub_id(tenant, KIND_PROJECT, 1))
        stages = (
            await db.execute(
                select(ProjectStage).where(ProjectStage.project_id == pp.id)
                .order_by(ProjectStage.position)
            )
        ).scalars().all()
        # Синтетической колонки-приёмника нет: задачи без колонки в WEEEK
        # приезжают без статуса (0046).
        assert [s.name for s in stages] == ["К работе", "Готово"]

        # Папку ищем ПО ССЫЛКЕ проекта, а не по тенанту: `ensure_folders`
        # сопоставляет портфель с папкой по имени (её мог завести человек),
        # а под superuser в тестах RLS не режет чужие тенанты.
        assert pp.folder_id is not None
        folder = await db.get(ProjectFolder, pp.folder_id)
        assert folder.name == "Отдел Персонала"
        # У проекта без портфеля папки нет — «Без папки» не выдумываем.
        design = await db.get(Project, hub_id(tenant, KIND_PROJECT, 2))
        assert design.folder_id is None

    async def test_owner_is_the_only_member_plus_resolvable_team(
        self, db: AsyncSession, imported
    ):
        tenant = imported["actor"].tenant_id
        pp = await db.get(Project, hub_id(tenant, KIND_PROJECT, 1))
        rows = (
            await db.execute(select(ProjectMember).where(ProjectMember.project_id == pp.id))
        ).scalars().all()
        by_employee = {m.employee_id: m.role for m in rows}
        assert by_employee[imported["actor"].employee_id] == "owner"
        # Команда WEEEK — редакторы: viewer менял бы только статус своей задачи.
        assert by_employee[imported["mate"].employee_id] == "editor"

    async def test_next_task_seq_is_above_every_imported_number(
        self, db: AsyncSession, imported
    ):
        # Иначе задача, созданная через UI посреди импорта, столкнулась бы с
        # UNIQUE (project_id, seq).
        rows = await db.execute(
            select(Project.key, Project.next_task_seq, func.max(Task.seq))
            .join(Task, Task.project_id == Project.id)
            .where(Project.tenant_id == imported["actor"].tenant_id)
            .group_by(Project.key, Project.next_task_seq)
        )
        for key, next_seq, max_seq in rows.all():
            assert next_seq > max_seq, key

    async def test_custom_field_only_in_its_project(self, db: AsyncSession, imported):
        tenant = imported["actor"].tenant_id
        defs = (
            await db.execute(
                select(CustomFieldDefinition).where(CustomFieldDefinition.tenant_id == tenant)
            )
        ).scalars().all()
        assert len(defs) == 1
        assert defs[0].name == "Контрагент"
        value = (
            await db.execute(
                select(TaskCustomFieldValue).where(TaskCustomFieldValue.tenant_id == tenant)
            )
        ).scalar_one()
        assert value.value == "ООО Ромашка"


class TestTasks:
    async def test_historical_dates_survive(self, db: AsyncSession, imported):
        task = await db.get(Task, hub_id(imported["actor"].tenant_id, KIND_TASK, 101))
        assert task.created_at.year == 2023
        # updated_at пишется явно: у колонки onupdate=now(), а поиск сортирует
        # по ней — иначе весь архив всплыл бы наверх выдачи.
        assert task.updated_at.year == 2023

    async def test_done_and_completed_at_are_a_pair(self, db: AsyncSession, imported):
        rows = (
            await db.execute(
                select(Task).where(Task.tenant_id == imported["actor"].tenant_id)
            )
        ).scalars().all()
        assert all(t.done == (t.completed_at is not None) for t in rows)
        closed = next(t for t in rows if t.done)
        assert closed.completed_at.year == 2023  # не «сегодня», как поставил бы set_done

    async def test_subtask_is_linked_inside_its_project(self, db: AsyncSession, imported):
        tenant = imported["actor"].tenant_id
        child = await db.get(Task, hub_id(tenant, KIND_TASK, 102))
        assert child.parent_task_id == hub_id(tenant, KIND_TASK, 101)

    async def test_no_task_whose_parent_is_itself_a_subtask(self, db: AsyncSession, imported):
        parent = Task.__table__.alias("p")
        rows = await db.execute(
            select(func.count())
            .select_from(Task.__table__.join(parent, parent.c.id == Task.parent_task_id))
            .where(parent.c.parent_task_id.is_not(None),
                   Task.tenant_id == imported["actor"].tenant_id)
        )
        assert rows.scalar_one() == 0

    async def test_cross_project_subtask_has_no_link_but_has_a_way_back(
        self, db: AsyncSession, imported
    ):
        tenant = imported["actor"].tenant_id
        task = await db.get(Task, hub_id(tenant, KIND_TASK, 201))
        # Связь оставила бы задачу невидимой: доска фильтрует !parent_task_id,
        # а список подзадач собирается из задач того же проекта.
        assert task.parent_task_id is None
        assert f"/projects/{hub_id(tenant, KIND_PROJECT, 1)}" in task.description
        assert f"?task={hub_id(tenant, KIND_TASK, 101)}" in task.description

    async def test_orphan_subtask_says_parent_was_not_imported(
        self, db: AsyncSession, imported
    ):
        task = await db.get(Task, hub_id(imported["actor"].tenant_id, KIND_TASK, 202))
        assert "родитель не перенесён" in task.description
        assert "/projects/" not in task.description

    async def test_task_without_a_column_in_weeek_arrives_without_a_status(
        self, db: AsyncSession, imported
    ):
        # 6 386 задач из 16 703 в WEEEK не лежали ни в одной колонке. Свалить
        # их в первую значило бы соврать, синтетическая колонка забивала доску —
        # поэтому у них просто нет статуса, и на доске их нет.
        tenant = imported["actor"].tenant_id
        task = await db.get(Task, hub_id(tenant, KIND_TASK, 103))
        assert task.stage_id is None

    async def test_every_task_sits_in_a_stage_of_its_own_project(
        self, db: AsyncSession, imported
    ):
        rows = await db.execute(
            select(func.count())
            .select_from(Task.__table__.join(
                ProjectStage.__table__, ProjectStage.id == Task.stage_id))
            .where(ProjectStage.project_id != Task.project_id,
                   Task.tenant_id == imported["actor"].tenant_id)
        )
        assert rows.scalar_one() == 0

    async def test_unknown_assignee_becomes_a_note(self, db: AsyncSession, imported):
        tenant = imported["actor"].tenant_id
        task = await db.get(Task, hub_id(tenant, KIND_TASK, 104))
        assert task.description.endswith("_Исполнитель в WEEEK: Андрей Доценко_")
        assert "Вложения в WEEEK: видео.mov." in task.description
        assigned = await db.execute(
            select(TaskAssignee).where(TaskAssignee.task_id == task.id)
        )
        assert assigned.first() is None

    async def test_untouched_description_has_no_provenance_block(
        self, db: AsyncSession, imported
    ):
        # У 13 тысяч задач из 16 703 терять нечего — текст остаётся как был.
        task = await db.get(Task, hub_id(imported["actor"].tenant_id, KIND_TASK, 103))
        assert task.description == "Тело"

    async def test_due_date_is_noon_display_tz(self, db: AsyncSession, imported):
        task = await db.get(Task, hub_id(imported["actor"].tenant_id, KIND_TASK, 102))
        assert task.due_at is not None
        assert task.due_at.hour == 9  # 12:00 Москвы = 09:00 UTC


class TestNoNotificationStorm:
    async def test_zero_creator_watchers(self, db: AsyncSession, imported):
        rows = await db.execute(
            select(func.count()).select_from(TaskWatcher).where(
                TaskWatcher.added_reason == "creator",
                TaskWatcher.tenant_id == imported["actor"].tenant_id,
            )
        )
        assert rows.scalar_one() == 0

    async def test_watcher_only_for_open_task_assignee(self, db: AsyncSession, imported):
        tenant = imported["actor"].tenant_id
        rows = (
            await db.execute(select(TaskWatcher).where(TaskWatcher.tenant_id == tenant))
        ).scalars().all()
        assert {w.task_id for w in rows} == {hub_id(tenant, KIND_TASK, 101)}
        assert rows[0].added_reason == "assignee"

    async def test_zero_notifications(self, db: AsyncSession, imported):
        assert await _count(db, Notification, imported["actor"].tenant_id) == 0


class TestAttachments:
    async def test_file_lands_on_disk_and_in_db(
        self, db: AsyncSession, imported, attachments_root
    ):
        from app.services.attachments import absolute_path

        tenant = imported["actor"].tenant_id
        rows = (
            await db.execute(
                select(TaskAttachment).where(TaskAttachment.tenant_id == tenant)
            )
        ).scalars().all()
        row = next(r for r in rows if r.task_id == hub_id(tenant, KIND_TASK, 101))
        assert row.filename == "счёт.png"  # оригинал, не «png» из санитайзера
        assert row.size_bytes == len(PNG)
        assert absolute_path(row.storage_key).read_bytes() == PNG

    async def test_storage_key_is_deterministic(self, db: AsyncSession, imported):
        tenant = imported["actor"].tenant_id
        rows = (
            await db.execute(
                select(TaskAttachment).where(TaskAttachment.tenant_id == tenant)
            )
        ).scalars().all()
        assert all("/att-1-" in r.storage_key for r in rows)

    async def test_same_file_on_two_tasks_gets_two_rows(self, db: AsyncSession, imported):
        # id вложения — пара (задача, файл): общий id ронял бы
        # task_attachments_pkey, и весь проект уходил бы в ошибку.
        tenant = imported["actor"].tenant_id
        rows = (
            await db.execute(
                select(TaskAttachment).where(TaskAttachment.tenant_id == tenant)
            )
        ).scalars().all()
        assert {r.task_id for r in rows} == {
            hub_id(tenant, KIND_TASK, 101), hub_id(tenant, KIND_TASK, 103)
        }
        assert len({r.storage_key for r in rows}) == 2


class TestIdempotency:
    async def test_second_run_changes_nothing(
        self, db: AsyncSession, tenant_id: uuid.UUID, imported
    ):
        models = (Task, ProjectStage, TaskAttachment, ProjectMember)
        before = {m.__name__: await _count(db, m, tenant_id) for m in models}
        again = await _run(db, tenant_id, imported["bundle"], imported["actor"].employee_id)
        assert again.stats["задач создано"] == 0
        assert again.stats["проектов уже было"] == 2
        after = {m.__name__: await _count(db, m, tenant_id) for m in models}
        assert after == before


class TestDryRun:
    async def test_nothing_is_written(
        self, db: AsyncSession, tenant_id: uuid.UUID, tmp_path: Path, attachments_root
    ):
        slug = f"weeek-dry-{uuid.uuid4().hex[:8]}"
        actor = make_principal(tenant_id, email=f"dry-{slug}@t.ru", tenant_slug=slug)
        await _register(db, actor, org_role="office")
        await db.commit()
        bundle = write_bundle(
            tmp_path, known_email=actor.email, unknown_email=f"unknown-{slug}@t.ru"
        )

        importer = await _run(db, tenant_id, bundle, actor.employee_id, apply=False)
        assert importer.stats["задач создано"] == 6

        assert await _count(db, Task, tenant_id) == 0
        assert list(attachments_root.rglob("*")) == []


class TestValidation:
    async def test_done_without_date_is_refused_before_any_insert(
        self, db: AsyncSession, tenant_id: uuid.UUID, tmp_path: Path, attachments_root
    ):
        # Иначе CHECK ck_tasks_done_completed_at уронил бы чанк на 500 задач.
        slug = f"weeek-bad-{uuid.uuid4().hex[:8]}"
        actor = make_principal(tenant_id, email=f"bad-{slug}@t.ru", tenant_slug=slug)
        await _register(db, actor, org_role="office")
        await db.commit()
        bundle = write_bundle(
            tmp_path, known_email=actor.email, unknown_email=f"unknown-{slug}@t.ru"
        )
        path = bundle / "projects/1.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["tasks"][0]["done"] = True
        payload["tasks"][0]["completed_at"] = None
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        with pytest.raises(SystemExit, match="done без даты"):
            await _run(db, tenant_id, bundle, actor.employee_id)
        assert await _count(db, Task, tenant_id) == 0

    async def test_long_option_id_is_refused(
        self, db: AsyncSession, tenant_id: uuid.UUID, tmp_path: Path, attachments_root
    ):
        """`CustomFieldOption.id` — max_length=32, в JSONB ограничения нет.

        Длинный id записался бы молча, а `GET /projects/{id}/custom-fields`
        после этого отдавал бы 500 на весь проект (staging, 25.08).
        """
        slug = f"weeek-opt-{uuid.uuid4().hex[:8]}"
        actor = make_principal(tenant_id, email=f"opt-{slug}@t.ru", tenant_slug=slug)
        await _register(db, actor, org_role="office")
        await db.commit()
        bundle = write_bundle(
            tmp_path, known_email=actor.email, unknown_email=f"unknown-{slug}@t.ru"
        )
        path = bundle / "manifest.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["projects"][0]["custom_fields"][0] = {
            "weeek_id": "cf-2", "name": "Статья", "type": "select", "position": 2,
            "options": [{"id": "9df70d73-176b-4e57-9770-354fd4e1d167", "label": "Аренда"}],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        with pytest.raises(SystemExit, match="длиннее 32"):
            await _run(db, tenant_id, bundle, actor.employee_id)
        assert await _count(db, Task, tenant_id) == 0

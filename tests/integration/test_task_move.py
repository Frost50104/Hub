"""Перенос задачи в другой проект (28.08).

`tasks.project_id` перестал быть иммутабельным, но цена, из-за которой он им
был, осталась: номер уникален внутри проекта, значит переезд перенумеровывает
задачу. Здесь проверяется и она, и всё, что привязано к СТАРОМУ проекту и
потому не может переехать как есть: колонка, метки, значения кастом-полей,
членство исполнителей, подписки, зависимости, уведомления и публичная ссылка.

Отдельно — что предпросмотр ничего не пишет: он живёт в диалоге и дёргается на
каждую смену цели.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.custom_fields import create_custom_field, set_task_custom_value
from app.api.dependencies import add_dependency
from app.api.labels import assign_label, create_label
from app.api.projects import create_project
from app.api.tasks import create_task, move_task, preview_task_move
from app.models.custom_field import TaskCustomFieldValue
from app.models.notification import Notification
from app.models.project import Project, ProjectMember
from app.models.share import PublicShareToken
from app.models.stage import ProjectStage
from app.models.task import Task, TaskActivity, TaskLabelAssignment, TaskWatcher
from app.schemas.custom_field import (
    CustomFieldDefinitionCreate,
    CustomFieldOption,
    CustomFieldValueSet,
)
from app.schemas.label import LabelCreate
from app.schemas.project import ProjectCreate
from app.schemas.task import TaskCreate, TaskMoveRequest
from app.services.personal_projects import ensure_personal_project
from tests.integration.conftest import make_principal, seed_stages
from tests.integration.test_project_access import _add_member, _register

pytestmark = pytest.mark.integration


async def _owner(db: AsyncSession, tenant_id: uuid.UUID, slug: str):
    person = make_principal(
        tenant_id, email=f"own-{slug}@t.ru", role="member", tenant_slug=slug
    )
    await _register(db, person, org_role="office")
    return person


async def _pair(db: AsyncSession, tenant_id: uuid.UUID, slug: str):
    """Два проекта одного владельца: источник и цель, у обоих по колонке."""
    owner = await _owner(db, tenant_id, slug)
    source = await create_project(ProjectCreate(name=f"Источник {slug}"), owner, db)
    target = await create_project(ProjectCreate(name=f"Цель {slug}"), owner, db)
    await seed_stages(db, source.id, owner, names=("Идея", "В работе"))
    await seed_stages(db, target.id, owner, names=("В работе", "Готово"))
    await db.commit()
    return owner, source, target


async def _stage_id(db: AsyncSession, project_id: uuid.UUID, name: str) -> uuid.UUID:
    return (
        await db.execute(
            select(ProjectStage.id).where(
                ProjectStage.project_id == project_id, ProjectStage.name == name
            )
        )
    ).scalar_one()


# ─── Номер, семья, позиция, колонка ─────────────────────────────────────────


async def test_move_changes_project_and_renumbers(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Номер уникален внутри проекта — переезд обязан его сменить."""
    owner, source, target = await _pair(db, tenant_id, "mv1")
    task = await create_task(source.id, TaskCreate(title="Переезд"), owner, db)
    await db.commit()
    old_seq = task.seq

    report = await move_task(task.id, TaskMoveRequest(project_id=target.id), owner, db)

    moved = await db.get(Task, task.id)
    assert moved is not None
    assert moved.project_id == target.id
    assert report.new_key == f"{target.key}-{moved.seq}"
    # Номер выдаёт целевой проект, а не переезжает вместе с задачей.
    assert moved.seq == 1
    assert (await db.get(Project, target.id)).next_task_seq == 2
    # Исходный проект номер не переиспользует — дыры допустимы (как в Jira).
    assert (await db.get(Project, source.id)).next_task_seq == old_seq + 1


async def test_subtasks_follow_the_parent_in_seq_order(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Разорванная семья означала бы `parent_task_id` в чужой проект."""
    owner, source, target = await _pair(db, tenant_id, "mv2")
    parent = await create_task(source.id, TaskCreate(title="Родитель"), owner, db)
    await db.commit()
    first = await create_task(
        source.id, TaskCreate(title="Первая", parent_task_id=parent.id), owner, db
    )
    second = await create_task(
        source.id, TaskCreate(title="Вторая", parent_task_id=parent.id), owner, db
    )
    await db.commit()

    report = await move_task(parent.id, TaskMoveRequest(project_id=target.id), owner, db)
    assert report.subtasks == 2

    rows = {
        t.id: t.seq
        for t in (
            await db.execute(select(Task).where(Task.project_id == target.id))
        ).scalars()
    }
    assert set(rows) == {parent.id, first.id, second.id}
    # Порядок создания внутри нового проекта сохранён.
    assert rows[parent.id] < rows[first.id] < rows[second.id]


async def test_subtask_alone_is_refused(db: AsyncSession, tenant_id: uuid.UUID):
    owner, source, target = await _pair(db, tenant_id, "mv3")
    parent = await create_task(source.id, TaskCreate(title="Родитель"), owner, db)
    await db.commit()
    child = await create_task(
        source.id, TaskCreate(title="Дочка", parent_task_id=parent.id), owner, db
    )
    await db.commit()

    with pytest.raises(HTTPException) as exc:
        await move_task(child.id, TaskMoveRequest(project_id=target.id), owner, db)
    assert exc.value.status_code == 409


async def test_position_is_recomputed_in_the_target(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Позиция из чужой шкалы поставила бы задачу в середину списка."""
    owner, source, target = await _pair(db, tenant_id, "mv4")
    stage = await _stage_id(db, target.id, "В работе")
    for i in range(3):
        await create_task(
            target.id, TaskCreate(title=f"Местная {i}", stage_id=stage), owner, db
        )
    await db.commit()
    task = await create_task(source.id, TaskCreate(title="Гостья"), owner, db)
    await db.commit()
    assert task.position < 3  # в источнике она первая

    await move_task(
        task.id, TaskMoveRequest(project_id=target.id, stage_id=stage), owner, db
    )

    moved = await db.get(Task, task.id)
    assert moved is not None
    others = (
        await db.execute(
            select(Task.position).where(
                Task.project_id == target.id, Task.id != task.id
            )
        )
    ).scalars().all()
    assert moved.position > max(others), "задача обязана встать в хвост колонки"


async def test_subtask_lands_on_the_same_named_column(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """`stage_id` подзадачи указывал бы на колонку ЧУЖОГО проекта."""
    owner, source, target = await _pair(db, tenant_id, "mv5")
    src_work = await _stage_id(db, source.id, "В работе")
    src_idea = await _stage_id(db, source.id, "Идея")
    parent = await create_task(source.id, TaskCreate(title="Родитель"), owner, db)
    await db.commit()
    same = await create_task(
        source.id,
        TaskCreate(title="Совпало", parent_task_id=parent.id, stage_id=src_work),
        owner,
        db,
    )
    lost = await create_task(
        source.id,
        TaskCreate(title="Не совпало", parent_task_id=parent.id, stage_id=src_idea),
        owner,
        db,
    )
    await db.commit()

    await move_task(parent.id, TaskMoveRequest(project_id=target.id), owner, db)

    assert (await db.get(Task, same.id)).stage_id == await _stage_id(
        db, target.id, "В работе"
    )
    # «Идеи» в цели нет — «без статуса» (0046), а не чужая колонка.
    assert (await db.get(Task, lost.id)).stage_id is None


# ─── Метки и кастом-поля ────────────────────────────────────────────────────


async def test_only_same_named_labels_survive(db: AsyncSession, tenant_id: uuid.UUID):
    owner, source, target = await _pair(db, tenant_id, "mv6")
    keep = await create_label(source.id, LabelCreate(name="Срочно"), owner, db)
    drop = await create_label(source.id, LabelCreate(name="Только тут"), owner, db)
    twin = await create_label(target.id, LabelCreate(name="Срочно"), owner, db)
    task = await create_task(source.id, TaskCreate(title="С метками"), owner, db)
    await db.commit()
    await assign_label(task.id, keep.id, owner, db)
    await assign_label(task.id, drop.id, owner, db)

    report = await move_task(task.id, TaskMoveRequest(project_id=target.id), owner, db)
    assert (report.labels_kept, report.labels_total) == (1, 2)

    labels = (
        await db.execute(
            select(TaskLabelAssignment.label_id).where(
                TaskLabelAssignment.task_id == task.id
            )
        )
    ).scalars().all()
    assert list(labels) == [twin.id]


async def test_custom_value_needs_name_and_type_to_match(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """По одному имени число уехало бы в текстовое поле."""
    owner, source, target = await _pair(db, tenant_id, "mv7")
    src_num = await create_custom_field(
        source.id, CustomFieldDefinitionCreate(name="Смета", type="number"), owner, db
    )
    dst_num = await create_custom_field(
        target.id, CustomFieldDefinitionCreate(name="Смета", type="number"), owner, db
    )
    src_txt = await create_custom_field(
        source.id, CustomFieldDefinitionCreate(name="Заметка", type="text"), owner, db
    )
    await create_custom_field(
        target.id, CustomFieldDefinitionCreate(name="Заметка", type="number"), owner, db
    )
    task = await create_task(source.id, TaskCreate(title="С полями"), owner, db)
    await db.commit()
    await set_task_custom_value(task.id, src_num.id, CustomFieldValueSet(value=42), owner, db)
    await set_task_custom_value(
        task.id, src_txt.id, CustomFieldValueSet(value="привет"), owner, db
    )

    report = await move_task(task.id, TaskMoveRequest(project_id=target.id), owner, db)
    assert (report.values_kept, report.values_total) == (1, 2)

    rows = (
        await db.execute(
            select(TaskCustomFieldValue.field_id, TaskCustomFieldValue.value).where(
                TaskCustomFieldValue.task_id == task.id
            )
        )
    ).all()
    assert rows == [(dst_num.id, 42.0)]


async def test_select_value_is_rebuilt_by_option_label(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """id опций у одноимённых полей свои — значение стало бы ссылкой в никуда."""
    owner, source, target = await _pair(db, tenant_id, "mv8")
    src = await create_custom_field(
        source.id,
        CustomFieldDefinitionCreate(
            name="Этап",
            type="select",
            options=[
                CustomFieldOption(id="s1", label="Черновик"),
                CustomFieldOption(id="s2", label="Только тут"),
            ],
        ),
        owner,
        db,
    )
    dst = await create_custom_field(
        target.id,
        CustomFieldDefinitionCreate(
            name="Этап",
            type="select",
            options=[CustomFieldOption(id="d9", label="Черновик")],
        ),
        owner,
        db,
    )
    resolvable = await create_task(source.id, TaskCreate(title="Разрешимая"), owner, db)
    orphan = await create_task(source.id, TaskCreate(title="Неразрешимая"), owner, db)
    await db.commit()
    await set_task_custom_value(
        resolvable.id, src.id, CustomFieldValueSet(value="s1"), owner, db
    )
    await set_task_custom_value(
        orphan.id, src.id, CustomFieldValueSet(value="s2"), owner, db
    )

    await move_task(resolvable.id, TaskMoveRequest(project_id=target.id), owner, db)
    await move_task(orphan.id, TaskMoveRequest(project_id=target.id), owner, db)

    kept = (
        await db.execute(
            select(TaskCustomFieldValue.field_id, TaskCustomFieldValue.value).where(
                TaskCustomFieldValue.task_id == resolvable.id
            )
        )
    ).all()
    assert kept == [(dst.id, "d9")], "опция пересобрана по лейблу, а не по id"
    assert (
        await db.execute(
            select(TaskCustomFieldValue.field_id).where(
                TaskCustomFieldValue.task_id == orphan.id
            )
        )
    ).scalars().all() == []


# ─── Доступ: исполнители, наблюдатели, уведомления ──────────────────────────


async def test_assignee_keeps_access_watcher_without_it_is_dropped(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Подписка на задачу, которую не открыть, ведёт по пушу в 403."""
    owner, source, target = await _pair(db, tenant_id, "mv9")
    doer = make_principal(tenant_id, email="doer-mv9@t.ru", tenant_slug="mv9")
    fan = make_principal(tenant_id, email="fan-mv9@t.ru", tenant_slug="mv9")
    await _register(db, doer)
    await _register(db, fan)
    await _add_member(db, tenant_id, source.id, doer, "editor")
    await _add_member(db, tenant_id, source.id, fan, "viewer")

    task = await create_task(
        source.id, TaskCreate(title="С людьми", assignee_ids=[doer.employee_id]), owner, db
    )
    await db.commit()
    db.add(
        TaskWatcher(
            task_id=task.id,
            employee_id=fan.employee_id,
            tenant_id=tenant_id,
            added_reason="manual",
        )
    )
    db.add(
        Notification(
            tenant_id=tenant_id,
            employee_id=fan.employee_id,
            kind="task.commented_on_watched",
            title="t",
            body="b",
            url=f"/projects/{source.id}?task={task.id}",
        )
    )
    db.add(
        Notification(
            tenant_id=tenant_id,
            employee_id=doer.employee_id,
            kind="task.assigned_to_me",
            title="t",
            body="b",
            url=f"/projects/{source.id}?task={task.id}",
        )
    )
    await db.commit()

    report = await move_task(task.id, TaskMoveRequest(project_id=target.id), owner, db)
    assert report.watchers_dropped == 1

    # Исполнитель получил членство в цели и остался наблюдателем.
    member = (
        await db.execute(
            select(ProjectMember.role).where(
                ProjectMember.project_id == target.id,
                ProjectMember.employee_id == doer.employee_id,
            )
        )
    ).scalar_one()
    assert member == "viewer"
    watchers = (
        await db.execute(
            select(TaskWatcher.employee_id).where(TaskWatcher.task_id == task.id)
        )
    ).scalars().all()
    assert fan.employee_id not in watchers

    urls = dict(
        (
            await db.execute(
                select(Notification.employee_id, Notification.url).where(
                    Notification.url.like(f"%task={task.id}")
                )
            )
        ).all()
    )
    # Оставшемуся ссылку переписали, отписанному строку убрали целиком.
    assert urls == {doer.employee_id: f"/projects/{target.id}?task={task.id}"}


async def test_the_mover_never_unsubscribes_themselves(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Права редактора в цели у переносящего только что проверены.

    Общее правило отписывает наблюдателей-неучастников (роль hub-admin лежит в
    JWT, по базе её не видно). Для САМОГО переносящего гадать не нужно — иначе
    админ отписывался от собственной задачи, а диалог честно предупреждал об
    этом (обнаружено на staging 28.08).
    """
    owner, source, target = await _pair(db, tenant_id, "mv19")
    admin = make_principal(
        tenant_id, email="adm-mv19@t.ru", role="admin", tenant_slug="mv19"
    )
    await _register(db, admin, org_role="office")
    task = await create_task(source.id, TaskCreate(title="Слежу за ней"), owner, db)
    await db.commit()
    db.add(
        TaskWatcher(
            task_id=task.id,
            employee_id=admin.employee_id,
            tenant_id=tenant_id,
            added_reason="manual",
        )
    )
    await db.commit()
    # Членства в цели у него нет — общее правило отписало бы его.
    assert (
        await db.execute(
            select(ProjectMember.employee_id).where(
                ProjectMember.project_id == target.id,
                ProjectMember.employee_id == admin.employee_id,
            )
        )
    ).scalar_one_or_none() is None

    report = await move_task(task.id, TaskMoveRequest(project_id=target.id), admin, db)

    assert report.watchers_dropped == 0
    watchers = (
        await db.execute(
            select(TaskWatcher.employee_id).where(TaskWatcher.task_id == task.id)
        )
    ).scalars().all()
    assert admin.employee_id in watchers


async def test_cross_project_dependency_is_removed(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """`api/dependencies.py` запрещает связи между проектами — переезд не
    должен оставлять на данных то, чего ручка не создаёт."""
    owner, source, target = await _pair(db, tenant_id, "mv10")
    first = await create_task(source.id, TaskCreate(title="Первая"), owner, db)
    second = await create_task(source.id, TaskCreate(title="Вторая"), owner, db)
    await db.commit()
    await add_dependency(second.id, first.id, owner, db)

    report = await move_task(first.id, TaskMoveRequest(project_id=target.id), owner, db)
    assert report.dependencies_dropped == 1

    from app.models.dependency import TaskDependency

    # Только свои строки: тесты, которые коммитят, живут в общем тенанте.
    left = (
        await db.execute(
            select(TaskDependency.predecessor_id).where(
                TaskDependency.predecessor_id.in_([first.id, second.id])
            )
        )
    ).scalars().all()
    assert list(left) == []


async def test_public_task_link_is_revoked(db: AsyncSession, tenant_id: uuid.UUID):
    """`_build_task_view` проект не смотрит: переезд в личное сделал бы личное
    публичным в обход `assert_not_personal`."""
    owner, source, target = await _pair(db, tenant_id, "mv11")
    task = await create_task(source.id, TaskCreate(title="Опубликованная"), owner, db)
    await db.commit()
    db.add(
        PublicShareToken(
            tenant_id=tenant_id,
            scope="task",
            entity_id=task.id,
            created_by=owner.employee_id,
        )
    )
    await db.commit()

    report = await move_task(task.id, TaskMoveRequest(project_id=target.id), owner, db)
    assert report.shares_revoked == 1

    revoked = (
        await db.execute(
            select(PublicShareToken.revoked_at).where(
                PublicShareToken.entity_id == task.id
            )
        )
    ).scalar_one()
    assert revoked is not None


async def test_target_with_a_public_link_is_flagged(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Задача станет видна анонимам без «явного акта над ней» — предупреждаем."""
    owner, source, target = await _pair(db, tenant_id, "mv12")
    task = await create_task(source.id, TaskCreate(title="Тихая"), owner, db)
    await db.commit()

    before = await preview_task_move(task.id, target.id, None, owner, db)
    assert before.target_public is False

    db.add(
        PublicShareToken(
            tenant_id=tenant_id,
            scope="project",
            entity_id=target.id,
            created_by=owner.employee_id,
            expires_at=datetime(2099, 1, 1, tzinfo=UTC),
        )
    )
    await db.commit()

    after = await preview_task_move(task.id, target.id, None, owner, db)
    assert after.target_public is True


# ─── Лента ──────────────────────────────────────────────────────────────────


async def test_activity_keeps_the_old_key(db: AsyncSession, tenant_id: uuid.UUID):
    """Единственный след старого номера: ссылки «PLP-118» больше не сойдутся."""
    owner, source, target = await _pair(db, tenant_id, "mv13")
    task = await create_task(source.id, TaskCreate(title="След"), owner, db)
    await db.commit()
    old_key = f"{source.key}-{task.seq}"

    await move_task(task.id, TaskMoveRequest(project_id=target.id), owner, db)

    payload = (
        await db.execute(
            select(TaskActivity.payload).where(
                TaskActivity.task_id == task.id, TaskActivity.kind == "moved"
            )
        )
    ).scalar_one()
    assert payload["from_key"] == old_key
    assert payload["from_project"] == source.name
    assert payload["to_project"] == target.name


# ─── Запреты ────────────────────────────────────────────────────────────────


async def test_same_project_and_archived_target_are_refused(
    db: AsyncSession, tenant_id: uuid.UUID
):
    owner, source, target = await _pair(db, tenant_id, "mv14")
    task = await create_task(source.id, TaskCreate(title="Никуда"), owner, db)
    await db.commit()

    with pytest.raises(HTTPException) as same:
        await move_task(task.id, TaskMoveRequest(project_id=source.id), owner, db)
    assert same.value.status_code == 400

    (await db.get(Project, target.id)).archived_at = datetime.now(UTC)
    await db.commit()
    with pytest.raises(HTTPException) as archived:
        await move_task(task.id, TaskMoveRequest(project_id=target.id), owner, db)
    assert archived.value.status_code == 409


async def test_editor_without_rights_in_the_target_is_refused(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Прав в источнике мало — иначе задачу можно затолкать в чужой проект."""
    owner, source, target = await _pair(db, tenant_id, "mv15")
    editor = make_principal(tenant_id, email="ed-mv15@t.ru", tenant_slug="mv15")
    await _register(db, editor)
    await _add_member(db, tenant_id, source.id, editor, "editor")
    task = await create_task(source.id, TaskCreate(title="Чужая цель"), owner, db)
    await db.commit()

    with pytest.raises(HTTPException) as exc:
        await move_task(task.id, TaskMoveRequest(project_id=target.id), editor, db)
    assert exc.value.status_code in (403, 404)


async def test_someone_elses_personal_is_refused_even_to_admin(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """`require_project_role` пропускает админа мимо членства, а
    `personal_task_scope` для него возвращает None — общий гейт не помешал бы."""
    owner, source, _target = await _pair(db, tenant_id, "mv16")
    admin = make_principal(
        tenant_id, email="adm-mv16@t.ru", role="admin", tenant_slug="mv16"
    )
    await _register(db, admin, org_role="office")
    personal_id = await ensure_personal_project(db, owner)
    await db.commit()
    assert personal_id is not None

    task = await create_task(source.id, TaskCreate(title="Чужое личное"), admin, db)
    await db.commit()

    with pytest.raises(HTTPException) as into:
        await move_task(task.id, TaskMoveRequest(project_id=personal_id), admin, db)
    assert into.value.status_code == 409

    mine = await create_task(personal_id, TaskCreate(title="Моя личная"), owner, db)
    await db.commit()
    with pytest.raises(HTTPException) as out_of:
        await move_task(mine.id, TaskMoveRequest(project_id=source.id), admin, db)
    assert out_of.value.status_code == 409


async def test_own_personal_moves_both_ways(db: AsyncSession, tenant_id: uuid.UUID):
    """Главный сценарий: записал у себя — отдал команде, и обратно."""
    owner, source, _target = await _pair(db, tenant_id, "mv17")
    personal_id = await ensure_personal_project(db, owner)
    await db.commit()
    assert personal_id is not None

    note = await create_task(personal_id, TaskCreate(title="Мысль"), owner, db)
    await db.commit()
    await move_task(note.id, TaskMoveRequest(project_id=source.id), owner, db)
    assert (await db.get(Task, note.id)).project_id == source.id

    await move_task(note.id, TaskMoveRequest(project_id=personal_id), owner, db)
    assert (await db.get(Task, note.id)).project_id == personal_id


# ─── Предпросмотр ───────────────────────────────────────────────────────────


async def test_preview_writes_nothing(db: AsyncSession, tenant_id: uuid.UUID):
    """Диалог дёргает его на каждую смену цели — номера жечь нельзя."""
    owner, source, target = await _pair(db, tenant_id, "mv18")
    label = await create_label(source.id, LabelCreate(name="Общая"), owner, db)
    await create_label(target.id, LabelCreate(name="Общая"), owner, db)
    task = await create_task(source.id, TaskCreate(title="Только смотрим"), owner, db)
    await db.commit()
    await assign_label(task.id, label.id, owner, db)
    before = (await db.get(Project, target.id)).next_task_seq

    report = await preview_task_move(task.id, target.id, None, owner, db)

    assert report.new_key is None, "номер выдаёт только сам перенос"
    assert (report.labels_kept, report.labels_total) == (1, 1)
    assert report.project_name == target.name
    await db.commit()
    assert (await db.get(Project, target.id)).next_task_seq == before
    assert (await db.get(Task, task.id)).project_id == source.id

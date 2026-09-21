"""Доступ к шаблонам (0060): роли, режим по методу, разбор пути, реестр ручек."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi.routing import APIRoute
from signaris_auth import Principal

from app.deps import _path_uuid, get_db_template_page, template_mode_for
from app.services.project_access import can_edit_template, template_role


def _p(role: str = "member") -> Principal:
    return Principal(
        employee_id=uuid.uuid4(),
        email="u@t.ru",
        tenant_id=uuid.uuid4(),
        tenant_slug="t",
        full_name="U",
        product_roles={"hub": role},
        jti=str(uuid.uuid4()),
    )


def test_template_role_ignores_roster():
    author, other, admin = _p(), _p(), _p("admin")
    project = SimpleNamespace(created_by=author.employee_id)
    assert template_role(author, project) == "owner"
    # Состав шаблона — будущие участники проектов, доступа он не даёт.
    assert template_role(other, project) == "viewer"
    assert template_role(admin, project) is None
    assert can_edit_template(author, author.employee_id)
    assert not can_edit_template(other, author.employee_id)
    assert can_edit_template(admin, author.employee_id)


def test_mode_by_method():
    assert template_mode_for("GET") == "view"
    assert template_mode_for("HEAD") == "view"
    for m in ("POST", "PUT", "PATCH", "DELETE"):
        assert template_mode_for(m) == "edit"


def test_path_uuid_tolerates_garbage():
    # Зависимость бежит ДО валидации пути: старый бандл на /projects/templates
    # не должен ронять запрос в 500.
    req = SimpleNamespace(path_params={"project_id": "templates"})
    assert _path_uuid(req, ("project_id",)) is None
    good = uuid.uuid4()
    req = SimpleNamespace(path_params={"task_id": str(good)})
    assert _path_uuid(req, ("project_id", "task_id")) == good


# Ручки, которым разрешено видеть шаблон. Всё остальное — шаринг, перенос,
# папки, архив, избранное, статистика, поиск, «Мои задачи» — видеть его НЕ
# должно: случайное подключение зависимости заметит этот тест.
EXPECTED = {
    ("GET", "/api/projects/{project_id}"),
    ("PATCH", "/api/projects/{project_id}"),
    ("DELETE", "/api/projects/{project_id}"),
    ("PUT", "/api/projects/{project_id}/badge"),
    ("POST", "/api/projects/{project_id}/badge/image"),
    ("GET", "/api/projects/{project_id}/members"),
    ("POST", "/api/projects/{project_id}/members"),
    ("PATCH", "/api/projects/{project_id}/members/{member_id}"),
    ("DELETE", "/api/projects/{project_id}/members/{member_id}"),
    ("GET", "/api/projects/{project_id}/tasks"),
    ("POST", "/api/projects/{project_id}/tasks"),
    ("GET", "/api/tasks/{task_id}"),
    ("PATCH", "/api/tasks/{task_id}"),
    ("DELETE", "/api/tasks/{task_id}"),
    ("PUT", "/api/tasks/{task_id}/recurrence"),
    ("DELETE", "/api/tasks/{task_id}/recurrence"),
    ("POST", "/api/tasks/{task_id}/assignees"),
    ("DELETE", "/api/tasks/{task_id}/assignees/{employee_id}"),
    ("POST", "/api/tasks/{task_id}/archive"),
    ("POST", "/api/tasks/{task_id}/unarchive"),
    ("GET", "/api/projects/{project_id}/stages"),
    ("POST", "/api/projects/{project_id}/stages"),
    ("PATCH", "/api/stages/{stage_id}"),
    ("DELETE", "/api/stages/{stage_id}"),
    ("GET", "/api/projects/{project_id}/labels"),
    ("POST", "/api/projects/{project_id}/labels"),
    ("PATCH", "/api/projects/{project_id}/labels/{label_id}"),
    ("DELETE", "/api/projects/{project_id}/labels/{label_id}"),
    ("GET", "/api/projects/{project_id}/label-assignments"),
    ("PUT", "/api/tasks/{task_id}/labels/{label_id}"),
    ("DELETE", "/api/tasks/{task_id}/labels/{label_id}"),
    ("GET", "/api/projects/{project_id}/custom-fields"),
    ("POST", "/api/projects/{project_id}/custom-fields"),
    ("PATCH", "/api/projects/{project_id}/custom-fields/{field_id}"),
    ("DELETE", "/api/projects/{project_id}/custom-fields/{field_id}"),
    ("GET", "/api/tasks/{task_id}/custom-fields"),
    ("GET", "/api/projects/{project_id}/custom-field-values"),
    ("PUT", "/api/tasks/{task_id}/custom-fields/{field_id}"),
    ("DELETE", "/api/tasks/{task_id}/custom-fields/{field_id}"),
    ("GET", "/api/tasks/{task_id}/watchers"),
    ("POST", "/api/tasks/{task_id}/watchers/me"),
    ("DELETE", "/api/tasks/{task_id}/watchers/me"),
    ("POST", "/api/tasks/{task_id}/watchers"),
    ("DELETE", "/api/tasks/{task_id}/watchers/{employee_id}"),
    ("GET", "/api/tasks/{task_id}/activity"),
    ("GET", "/api/tasks/{task_id}/dependencies"),
    ("POST", "/api/tasks/{successor_id}/dependencies/{predecessor_id}"),
    ("DELETE", "/api/tasks/{successor_id}/dependencies/{predecessor_id}"),
    ("GET", "/api/tasks/{task_id}/attachments"),
    ("POST", "/api/attachments"),
    ("POST", "/api/tasks/{task_id}/attachments"),
    ("GET", "/api/attachments/{attachment_id}/download"),
    ("DELETE", "/api/attachments/{attachment_id}"),
    ("GET", "/api/tasks/{task_id}/comments"),
    ("POST", "/api/tasks/{task_id}/comments"),
    ("PATCH", "/api/comments/{comment_id}"),
    ("DELETE", "/api/comments/{comment_id}"),
    ("GET", "/api/projects/{project_id}/tasks/calendar"),
    ("GET", "/api/projects/{project_id}/timeline"),
    ("POST", "/api/projects/{project_id}/tasks/import"),
}

FORBIDDEN_FRAGMENTS = ("/share", "/move", "/folder", "/archive", "/favorite", "/stats")


def _uses_template_dependency(route: APIRoute) -> bool:
    stack = list(route.dependant.dependencies)
    while stack:
        d = stack.pop()
        if d.call is get_db_template_page:
            return True
        stack.extend(d.dependencies)
    return False


@pytest.fixture(scope="module")
def routes() -> list[tuple[str, APIRoute]]:
    """(полный путь, ручка) из роутеров модулей `app/api`, а не из `app.routes`.

    С FastAPI 0.140+ `include_router` больше не разворачивает ручки в
    `app.routes` (там лежат обёртки `_IncludedRouter`), и тест, читавший их,
    молча видел ноль ручек — в CI (свежий FastAPI) он падал, локально (0.136)
    проходил. `router.routes` модуля — публичный и одинаковый в обеих версиях;
    все роутеры подключены в `app/main.py` с префиксом `/api`.
    """
    import importlib
    import pkgutil

    from fastapi import APIRouter

    import app.api as api_pkg

    out: list[tuple[str, APIRoute]] = []
    for info in pkgutil.iter_modules(api_pkg.__path__):
        router = getattr(importlib.import_module(f"app.api.{info.name}"), "router", None)
        if not isinstance(router, APIRouter):
            continue
        out += [("/api" + r.path, r) for r in router.routes if isinstance(r, APIRoute)]
    return out


def test_template_dependency_registry(routes):
    # Страховка от повторения той же ошибки: пустой обход проходил бы тест
    # «запрещённые ручки шаблон не открывают» просто потому, что ручек нет.
    assert len(routes) > 100
    actual = {
        (m, path) for path, r in routes if _uses_template_dependency(r) for m in r.methods
    }
    assert actual == EXPECTED


def test_forbidden_routes_do_not_open_templates(routes):
    assert len(routes) > 100
    for path, r in routes:
        if not _uses_template_dependency(r):
            continue
        tail = path.split("{project_id}")[-1].split("{task_id}")[-1]
        # Архив задачи (не проекта) — легальная правка задачи шаблона.
        if path.startswith("/api/tasks/"):
            continue
        assert not any(f in tail for f in FORBIDDEN_FRAGMENTS), path


async def test_notify_is_silent_for_template_tasks(monkeypatch):
    import app.services.notify as notify

    calls: list[dict] = []

    async def fake_dispatch(session, **kw):
        calls.append(kw)

    monkeypatch.setattr(notify, "dispatch", fake_dispatch)
    task = SimpleNamespace(
        id=uuid.uuid4(), project_id=uuid.uuid4(), tenant_id=uuid.uuid4(),
        title="Т", is_template=True, due_at=None,
    )
    await notify.notify_assigned(None, task=task, assignee_id=uuid.uuid4(), actor_name="А")
    await notify.notify_overdue(None, task=task, recipient_id=uuid.uuid4())
    assert calls == []
    task.is_template = False
    await notify.notify_assigned(None, task=task, assignee_id=uuid.uuid4(), actor_name="А")
    assert len(calls) == 1


async def test_move_refuses_templates():
    from fastapi import HTTPException

    from app.services.task_move import assert_movable

    src_id, dst_id = uuid.uuid4(), uuid.uuid4()
    task = SimpleNamespace(parent_task_id=None, project_id=src_id)
    live = SimpleNamespace(
        id=dst_id, is_template=False, archived_at=None, personal_owner_id=None
    )
    tpl = SimpleNamespace(
        id=src_id, is_template=True, archived_at=None, personal_owner_id=None
    )
    with pytest.raises(HTTPException) as exc:
        await assert_movable(task=task, source=tpl, target=live, principal=_p())
    assert exc.value.status_code == 409

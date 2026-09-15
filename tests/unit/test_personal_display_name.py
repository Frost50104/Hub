"""Имя личного проекта глазами того, кто его открыл.

С 16.09 все личные проекты называются «Мои задачи» — экран и проект стали одним
и тем же. Гостю (автору поручения, которому выдали viewer-членство) это имя
показывать нельзя: он прочитал бы «Проект: Мои задачи» про чужой инбокс.

Чистая функция без запросов — тестируется без контейнера, как
`tests/unit/test_delegated_access.py`.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.services.personal_projects import personal_display_name

ME = uuid.uuid4()
OTHER = uuid.uuid4()


def _principal(employee_id=ME):
    return SimpleNamespace(employee_id=employee_id)


def _project(owner):
    return SimpleNamespace(name="Мои задачи", personal_owner_id=owner)


def test_own_personal_keeps_name():
    assert personal_display_name(_project(ME), _principal()) == "Мои задачи"


def test_work_project_keeps_name():
    project = SimpleNamespace(name="Маркетинг", personal_owner_id=None)
    assert personal_display_name(project, _principal()) == "Маркетинг"


def test_foreign_personal_is_renamed_for_the_guest():
    got = personal_display_name(
        _project(OTHER), _principal(), owner_name="Диана Карпович"
    )
    assert got == "Личное · Диана Карпович"


def test_foreign_personal_without_owner_name():
    """Имя владельца не приехало — говорим «Личное», а не «Мои задачи».

    Второе прямо врёт, и это хуже неполноты.
    """
    assert personal_display_name(_project(OTHER), _principal()) == "Личное"

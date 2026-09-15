"""Право автора на ПОРУЧЕННУЮ задачу в чужом личном пространстве.

Запрос владельца 15.09: «создавать задачу прямо в личные задачи исполнителю,
чтобы её видел только исполнитель и автор». Видимость даёт уже существующий
`personal_task_scope` (ветка «я наблюдатель»), а вот правка и отзыв — нет:
автор там viewer. Правило узкое и потому проверяется отдельно.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.services.personal_projects import may_edit_delegated

AUTHOR = uuid.UUID("11111111-1111-4111-8111-111111111111")
OWNER = uuid.UUID("22222222-2222-4222-8222-222222222222")
STRANGER = uuid.UUID("33333333-3333-4333-8333-333333333333")


def _task(created_by: uuid.UUID):
    return SimpleNamespace(created_by=created_by)


def _project(personal_owner_id: uuid.UUID | None):
    return SimpleNamespace(personal_owner_id=personal_owner_id)


def _principal(employee_id: uuid.UUID):
    return SimpleNamespace(employee_id=employee_id)


def test_author_edits_own_delegated_task():
    assert may_edit_delegated(_task(AUTHOR), _project(OWNER), _principal(AUTHOR))


def test_stranger_does_not_edit_someone_elses_delegation():
    # Тот, кто оказался в чужом личном по другой причине (назначение,
    # упоминание), чужую поручённую задачу править не должен.
    assert not may_edit_delegated(_task(AUTHOR), _project(OWNER), _principal(STRANGER))


def test_owner_of_personal_goes_by_normal_rules():
    # У владельца личного и так owner-роль: правило не должно подменять её
    # собой, иначе «его» задачи начали бы считаться поручениями.
    assert not may_edit_delegated(_task(OWNER), _project(OWNER), _principal(OWNER))


def test_rule_does_not_leak_into_work_projects():
    # Обычный проект: автор задачи НЕ получает прав редактора — там гейт
    # решает роль в проекте, и ослаблять его нельзя.
    assert not may_edit_delegated(_task(AUTHOR), _project(None), _principal(AUTHOR))


def test_author_of_own_personal_task_is_not_delegation():
    # Задача в СВОЁМ личном: владелец и автор совпадают, поручения нет.
    assert not may_edit_delegated(_task(AUTHOR), _project(AUTHOR), _principal(AUTHOR))

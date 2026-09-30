"""Адрес карточки задачи — один формат на весь сервер (`services/task_links.py`).

От формата зависят чистки уведомлений по суффиксу `?task={id}` (удаление и
перенос задачи) и по префиксу `/projects/{p}` (удаление проекта), а на фронте —
`taskIdFromHref`. Интеграционные тесты сверяют готовые строки, но в CI не
бегут; этот тест — единственная проверка формата в CI.
"""

from __future__ import annotations

import uuid

from app.services.task_links import task_url

PROJECT = uuid.UUID("d29e1f2c-636e-49d8-b477-2e32feedeec2")
TASK = uuid.UUID("2f597ed8-2c25-4a04-958d-2317b87f412f")


def test_task_url_format():
    url = task_url(PROJECT, TASK)
    assert url == f"/projects/{PROJECT}?task={TASK}"
    # Префикс — чистка при удалении проекта, суффикс — при удалении и переносе задачи.
    assert url.startswith(f"/projects/{PROJECT}")
    assert url.endswith(f"task={TASK}")


def test_task_url_accepts_strings():
    """Разовый импорт из WEEEK собирает ссылки из строковых id."""
    assert task_url(str(PROJECT), str(TASK)) == task_url(PROJECT, TASK)


def test_never_points_to_missing_tasks_route():
    """Маршрута `/tasks/{id}` у фронта нет — неизвестный путь уводит на главную."""
    assert not task_url(PROJECT, TASK).startswith("/tasks/")

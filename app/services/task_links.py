"""Адрес карточки задачи — один формат на весь сервер.

`/projects/{project_id}?task={task_id}`: фронт открывает карточку поверх
страницы проекта, а свой личный проект редиректит на «Мои задачи», сохраняя
`?task=` (`web/src/lib/myTasksTabs.ts::personalProjectRedirect`).

От формата зависят не только ссылки:

- суффикс `?task={id}` — чистки уведомлений при удалении задачи
  (`api/tasks.py::delete_task`, `LIKE '%task={id}'`) и при переносе
  (`services/task_move.py`);
- префикс `/projects/{p}` — чистка при удалении проекта (`api/projects.py`,
  `LIKE '/projects/{p}%'`);
- `taskIdFromHref` на фронте (`web/src/lib/taskLinks.ts`) достаёт задачу из
  адреса пуша и «Входящих», чтобы перечитать её обсуждение.

Маршрута `/tasks/{id}` у фронта НЕТ: неизвестный путь уводит на главную. Именно
так до 28.09 работала ссылка ассистента после комментария.

Без импортов из `app`: модуль зовут уведомления, напоминания, перенос задачи,
ассистент и разовый импорт из WEEEK.
"""

from __future__ import annotations

from uuid import UUID


def task_url(project_id: UUID | str, task_id: UUID | str) -> str:
    return f"/projects/{project_id}?task={task_id}"

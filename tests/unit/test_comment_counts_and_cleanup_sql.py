"""Удалённый комментарий не считается и снимает свои уведомления (ОС 08.09, RH-23).

Компиляция в SQL диалекта Postgres — без контейнера и в CI: интеграционные
тесты (`tests/integration/test_comment_delete_notifications.py`,
`test_task_counts.py`) CI не гоняет, а регресс здесь тихий — строка списка
снова пообещает «2 комментария» над обсуждением из одного.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.dialects import postgresql

from app.models.task import TaskComment
from app.services.notify import COMMENT_NOTIFICATION_KINDS, comment_notifications_where
from app.services.task_counts import comment_counts_stmt

TASK = uuid.UUID("2f597ed8-2c25-4a04-958d-2317b87f412f")
COMMENT = uuid.UUID("599e3a06-f43c-4301-b270-ee745bb353d5")
CREATED = datetime(2026, 9, 8, 10, 16, 50, 316800, tzinfo=UTC)


def _compiled(expr):
    return expr.compile(dialect=postgresql.dialect())


def test_comment_counter_skips_deleted():
    sql = str(_compiled(comment_counts_stmt([TASK])))
    assert "task_comments.deleted_at IS NULL" in sql
    assert "GROUP BY task_comments.task_id" in sql


def test_cleanup_matches_by_comment_id_or_legacy_pair():
    comment = TaskComment(id=COMMENT, task_id=TASK, created_at=CREATED)
    compiled = _compiled(comment_notifications_where(comment))
    sql = str(compiled)
    params = list(compiled.params.values())

    # Только виды, которые рождает комментарий: «назначили» и «выполнено»
    # по той же задаче удаление комментария не трогает.
    assert "notifications.kind IN" in sql
    assert list(COMMENT_NOTIFICATION_KINDS) in params
    assert set(COMMENT_NOTIFICATION_KINDS) == {"task.mentioned", "task.commented_on_watched"}

    # Новые строки — по comment_id; старые (без него) — пара задача + created_at.
    assert sql.count("->>") == 3
    assert "IS NULL" in sql
    assert "notifications.created_at =" in sql
    assert "comment_id" in params
    assert "task_id" in params
    assert str(COMMENT) in params
    assert str(TASK) in params
    assert CREATED in params

    # Не по URL: перенос задачи переписывает ссылку, а payload — нет.
    assert "notifications.url" not in sql

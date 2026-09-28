"""Счётчики строки списка задач (редизайн трекера).

Строка контекста в списке обещает «2 комментария», «1 вложение» и «зависит от
задачи». Держать это в самой выборке нельзя: JOIN размножил бы строку задачи по
числу комментариев (дубли карточек на доске и поехавшая сортировка — тот же
инвариант, что у исполнителей). Поэтому считаем батчем по id, как
`task_assignees.load_assignees`.

Счётчики нужны только списку. Одиночные ручки (`get`/`create`/`update`) их не
заполняют и отдают `None` — «не знаем», чтобы клиент не рисовал чип «0».
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import ColumnElement, Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attachment import TaskAttachment
from app.models.dependency import TaskDependency
from app.models.task import TaskComment

_CHUNK = 1000


@dataclass(frozen=True)
class RowCounts:
    comments: int
    attachments: int
    blockers: int


def _counts_stmt(column, chunk: Sequence[UUID], *where: ColumnElement[bool]) -> Select:
    return (
        select(column, func.count())
        .where(column.in_(chunk), *where)
        .group_by(column)
    )


def comment_counts_stmt(chunk: Sequence[UUID]) -> Select:
    """Только живые комментарии: удалённый карточка не показывает
    (`comments.py::_list_with_authors`), и строка списка, считавшая его,
    обещала «2 комментария» над обсуждением из одного (ОС 08.09, RH-23).

    Сборка отделена от исполнения ради юнит-теста на компиляцию SQL:
    интеграционные тесты в CI не бегут.
    """
    return _counts_stmt(
        TaskComment.task_id, chunk, TaskComment.deleted_at.is_(None)
    )


async def _count_by(
    db: AsyncSession, build, table_ids: Sequence[UUID]
) -> dict[UUID, int]:
    out: dict[UUID, int] = {}
    for start in range(0, len(table_ids), _CHUNK):
        chunk = table_ids[start : start + _CHUNK]
        rows = await db.execute(build(chunk))
        for key, count in rows.all():
            out[key] = count
    return out


async def load_row_counts(
    db: AsyncSession, task_ids: Sequence[UUID]
) -> dict[UUID, RowCounts]:
    """{task_id: RowCounts} тремя запросами на чанк.

    `blockers` — число задач, которых ЖДЁТ эта (она successor), а не тех, что
    ждут её: строка списка сообщает «зависит от задачи», словарь берётся из
    TaskDependencies.tsx.
    """
    ids = list(dict.fromkeys(task_ids))
    if not ids:
        return {}
    comments = await _count_by(db, comment_counts_stmt, ids)
    # У вложений и зависимостей мягкого удаления нет — считаем все строки.
    attachments = await _count_by(
        db, lambda chunk: _counts_stmt(TaskAttachment.task_id, chunk), ids
    )
    blockers = await _count_by(
        db, lambda chunk: _counts_stmt(TaskDependency.successor_id, chunk), ids
    )
    return {
        task_id: RowCounts(
            comments=comments.get(task_id, 0),
            attachments=attachments.get(task_id, 0),
            blockers=blockers.get(task_id, 0),
        )
        for task_id in ids
    }

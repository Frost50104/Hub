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

from sqlalchemy import func, select
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


async def _count_by(
    db: AsyncSession, column, table_ids: Sequence[UUID]
) -> dict[UUID, int]:
    out: dict[UUID, int] = {}
    for start in range(0, len(table_ids), _CHUNK):
        chunk = table_ids[start : start + _CHUNK]
        rows = await db.execute(
            select(column, func.count())
            .where(column.in_(chunk))
            .group_by(column)
        )
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
    comments = await _count_by(db, TaskComment.task_id, ids)
    attachments = await _count_by(db, TaskAttachment.task_id, ids)
    blockers = await _count_by(db, TaskDependency.successor_id, ids)
    return {
        task_id: RowCounts(
            comments=comments.get(task_id, 0),
            attachments=attachments.get(task_id, 0),
            blockers=blockers.get(task_id, 0),
        )
        for task_id in ids
    }

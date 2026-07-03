"""Ранжирование приоритета для сортировки списка задач."""

from typing import get_args

from app.api.tasks import PRIORITY_ORDER, TaskSortField
from app.schemas.task import TaskPriority


def test_priority_rank_monotonic():
    assert (
        PRIORITY_ORDER["low"]
        < PRIORITY_ORDER["medium"]
        < PRIORITY_ORDER["high"]
        < PRIORITY_ORDER["urgent"]
    )


def test_priority_rank_covers_all_enum_values():
    assert set(PRIORITY_ORDER) == set(get_args(TaskPriority))


def test_sort_fields_are_known():
    assert set(get_args(TaskSortField)) == {
        "position",
        "due_at",
        "priority",
        "created_at",
        "title",
    }

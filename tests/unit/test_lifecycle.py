"""Юнит-тесты lifecycle-переходов контента (Ф1, ТЗ §25)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

import pytest
from fastapi import HTTPException

from app.services.lifecycle import can, transition


@dataclass
class FakeMaterial:
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    status: str = "draft"
    published_at: datetime | None = None
    archived_at: datetime | None = None
    review_period_months: int | None = None
    next_review_at: datetime | None = None


class FakeDB:
    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)


def _t(obj, new_status, role, db=None):
    transition(
        db or FakeDB(),
        obj,
        new_status,
        actor_id=uuid.uuid4(),
        role=role,
        tenant_id=uuid.uuid4(),
        object_type="library_material",
        object_label="Тест",
    )


def test_author_can_submit_to_review():
    m = FakeMaterial()
    _t(m, "review", "author")
    assert m.status == "review"


def test_author_cannot_publish():
    m = FakeMaterial()
    with pytest.raises(HTTPException) as e:
        _t(m, "published", "author")
    assert e.value.status_code == 403
    assert m.status == "draft"


def test_publisher_publish_sets_published_at_and_review_date():
    m = FakeMaterial(review_period_months=6)
    _t(m, "published", "publisher")
    assert m.status == "published"
    assert m.published_at is not None
    assert m.next_review_at is not None
    assert (m.next_review_at - m.published_at).days == 180


def test_admin_equals_publisher():
    m = FakeMaterial()
    _t(m, "published", "admin")
    assert m.status == "published"


def test_invalid_transition_rejected():
    m = FakeMaterial(status="draft")
    with pytest.raises(HTTPException) as e:
        _t(m, "archived", "admin")  # draft → archived не существует
    assert e.value.status_code == 422


def test_archive_and_republish():
    m = FakeMaterial(status="published", published_at=datetime(2026, 1, 1))
    _t(m, "archived", "publisher")
    assert m.archived_at is not None
    _t(m, "published", "publisher")
    assert m.status == "published"
    assert m.archived_at is None
    # Re-publish обновляет published_at (от него считаются дедлайны).
    assert m.published_at.year == 2026 and m.published_at.month != 1


def test_none_role_cannot_do_anything():
    m = FakeMaterial()
    with pytest.raises(HTTPException):
        _t(m, "review", "none")


def test_audit_row_written():
    m = FakeMaterial()
    db = FakeDB()
    _t(m, "review", "author", db=db)
    assert len(db.added) == 1
    assert db.added[0].action == "update"
    assert db.added[0].diff == {"status": {"old": "draft", "new": "review"}}


def test_can_ranking():
    assert can("admin", "publisher")
    assert can("publisher", "author")
    assert not can("author", "publisher")
    assert not can("none", "author")

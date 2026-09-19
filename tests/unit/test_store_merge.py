"""Рекомендация победителя при слиянии карточек (`store_merge.recommend_winner`)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.services.store_merge import StoreStats, recommend_winner

T0 = datetime(2026, 7, 23, tzinfo=UTC)


def _s(people, race=False, age_days=0):
    return StoreStats(uuid4(), people, race, T0 + timedelta(days=age_days))


def test_more_people_wins_even_if_younger():
    old, young = _s(1), _s(2, age_days=36)
    assert recommend_winner(old, young) == young.store_id


def test_race_participation_breaks_a_tie_then_age():
    a, b = _s(0, race=False), _s(0, race=True, age_days=36)
    assert recommend_winner(a, b) == b.store_id
    a, b = _s(3), _s(3, age_days=36)
    assert recommend_winner(a, b) == a.store_id, "при равенстве — старшая"

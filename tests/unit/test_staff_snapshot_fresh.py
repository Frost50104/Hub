"""Свежесть снимка штата (совет auth в HUB_TASK_staff_endpoint_REPLY.md).

«Был хоть один синк» — залипающий флаг: сломайся ключ, экран неделю писал бы
«без учётки» по устаревшему снимку. Живой снимок = не старше двух интервалов.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.api.employees import auth_state_for, staff_snapshot_fresh

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)


def test_snapshot_freshness_window() -> None:
    assert staff_snapshot_fresh(None, now=NOW, interval_sec=900.0) is False
    fresh = NOW - timedelta(minutes=29)
    stale = NOW - timedelta(minutes=31)
    assert staff_snapshot_fresh(fresh, now=NOW, interval_sec=900.0) is True
    assert staff_snapshot_fresh(stale, now=NOW, interval_sec=900.0) is False


def test_stale_snapshot_downgrades_no_account_to_not_linked() -> None:
    """Протухший снимок откатывает уверенное «без учётки» к осторожному
    «не привязан(а)» — по устаревшим данным утверждать нельзя."""
    kw = dict(
        employee_id=None,
        last_activity_at=None,
        shadow_deleted=False,
        auth_active=None,
    )
    assert auth_state_for(staff_synced=True, **kw) == "no_account"
    assert auth_state_for(staff_synced=False, **kw) == "not_linked"

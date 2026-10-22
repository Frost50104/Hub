"""Коды здоровья конвейера видео (`/api/health/media`) — чистые правила без БД."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.services.media import health as h

NOW = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)


def _snap(**kw):
    base = {
        "ffmpeg_present": True,
        "stt_configured": True,
        "avatar_flag": False,
        "hedra_key_present": False,
        "oldest_queued_at": None,
        "running_count": 0,
        "expired_running": 0,
        "failed_last_24h": 0,
        "hedra_auth_failed": False,
    }
    base.update(kw)
    return h.MediaHealthSnapshot(**base)


def test_healthy_snapshot_has_no_problems():
    assert h.health_problems(_snap(), now=NOW) == []


def test_missing_binaries_and_stt_are_reported():
    assert h.health_problems(_snap(ffmpeg_present=False), now=NOW) == ["ffmpeg_missing"]
    assert h.health_problems(_snap(stt_configured=False), now=NOW) == ["stt_unconfigured"]


def test_hedra_key_is_required_only_when_avatar_flag_is_on():
    assert h.health_problems(_snap(avatar_flag=True), now=NOW) == ["hedra_key_missing"]
    assert h.health_problems(_snap(avatar_flag=True, hedra_key_present=True), now=NOW) == []
    assert h.health_problems(_snap(avatar_flag=False, hedra_key_present=False), now=NOW) == []


def test_queue_is_stale_only_when_old_and_nothing_runs():
    fresh = _snap(oldest_queued_at=NOW - timedelta(minutes=5))
    assert h.health_problems(fresh, now=NOW) == []
    old_but_busy = _snap(oldest_queued_at=NOW - timedelta(hours=2), running_count=1)
    assert h.health_problems(old_but_busy, now=NOW) == []
    stale = _snap(oldest_queued_at=NOW - timedelta(hours=2))
    assert h.health_problems(stale, now=NOW) == ["queue_stale"]


def test_expired_lease_failed_burst_and_hedra_auth():
    assert h.health_problems(_snap(expired_running=1), now=NOW) == ["lease_expired"]
    assert h.health_problems(_snap(failed_last_24h=2), now=NOW) == []
    assert h.health_problems(_snap(failed_last_24h=3), now=NOW) == ["failed_burst"]
    assert h.health_problems(_snap(hedra_auth_failed=True), now=NOW) == ["hedra_auth"]


def test_problems_are_sorted_in_a_stable_order():
    everything = _snap(
        ffmpeg_present=False,
        stt_configured=False,
        avatar_flag=True,
        oldest_queued_at=NOW - timedelta(hours=1),
        expired_running=2,
        failed_last_24h=9,
        hedra_auth_failed=True,
    )
    assert h.health_problems(everything, now=NOW) == [
        "ffmpeg_missing",
        "stt_unconfigured",
        "hedra_key_missing",
        "queue_stale",
        "lease_expired",
        "failed_burst",
        "hedra_auth",
    ]

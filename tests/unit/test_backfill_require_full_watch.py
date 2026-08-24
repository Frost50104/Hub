"""Патч видео-нод: ключ ставится только там, где его нет вовсе."""

from __future__ import annotations

from uuid import uuid4

from app.jobs.backfill_require_full_watch import ensure_require_full_watch
from app.services.lesson_content import collect_required_videos, validate_lesson_content

MEDIA = str(uuid4())


def _doc(*nodes: dict) -> dict:
    return {"schema": 1, "doc": {"type": "doc", "content": list(nodes)}}


def test_missing_key_is_set():
    payload = _doc({"type": "video", "attrs": {"mediaId": MEDIA}})
    patched, added, explicit = ensure_require_full_watch(payload)
    assert (added, explicit) == (1, 0)
    assert collect_required_videos(patched) == [MEDIA]


def test_explicit_false_left_alone():
    payload = _doc({"type": "video", "attrs": {"mediaId": MEDIA, "requireFullWatch": False}})
    patched, added, explicit = ensure_require_full_watch(payload)
    assert (added, explicit) == (0, 1)
    assert collect_required_videos(patched) == []


def test_explicit_true_is_not_counted_twice():
    payload = _doc({"type": "video", "attrs": {"mediaId": MEDIA, "requireFullWatch": True}})
    _patched, added, explicit = ensure_require_full_watch(payload)
    assert (added, explicit) == (0, 0)


def test_nested_node_found():
    payload = _doc(
        {
            "type": "callout",
            "attrs": {"kind": "important"},
            "content": [{"type": "video", "attrs": {"mediaId": MEDIA}}],
        }
    )
    patched, added, _ = ensure_require_full_watch(payload)
    assert added == 1
    assert collect_required_videos(patched) == [MEDIA]


def test_source_not_mutated():
    # SQLAlchemy не увидит правку JSONB «на месте» (объект тот же) и молча не
    # запишет ничего — поэтому патч обязан возвращать НОВЫЙ объект.
    payload = _doc({"type": "video", "attrs": {"mediaId": MEDIA}})
    patched, _added, _ = ensure_require_full_watch(payload)
    assert "requireFullWatch" not in payload["doc"]["content"][0]["attrs"]
    assert patched is not payload


def test_result_passes_server_validator():
    payload = _doc(
        {"type": "paragraph", "content": [{"type": "text", "text": "Смотри"}]},
        {"type": "video", "attrs": {"mediaId": MEDIA}},
    )
    patched, _added, _ = ensure_require_full_watch(payload)
    validate_lesson_content(patched)


def test_video_without_attrs_survives():
    payload = _doc({"type": "video"})
    patched, added, _ = ensure_require_full_watch(payload)
    assert added == 1
    # mediaId нет — гейта всё равно не будет, но и падать не должны.
    assert collect_required_videos(patched) == []


def test_audit_action_fits_the_column():
    # Длинное имя роняло прогон на commit — уже после всей работы, целиком.
    from app.jobs.backfill_require_full_watch import AUDIT_ACTION
    from app.models.audit import AuditLog

    limit = AuditLog.__table__.c.action.type.length
    assert limit is not None
    assert len(AUDIT_ACTION) <= limit

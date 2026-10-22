"""Документы уроков в поиске (0066): зеркало меток, сбор видео-нод, серверные
атрибуты `trackSrc`/`status`, SQL поиска уроков по mediaId."""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from sqlalchemy.dialects import postgresql

from app.api.learn_search import OBJECT_TYPE_LABEL
from app.services import course_index
from app.services.lesson_content import collect_video_ids, prepare_for_consumer

ROOT = Path(__file__).resolve().parents[2]


def test_object_type_labels_are_mirrored_in_frontend():
    ts = (ROOT / "web" / "src" / "lib" / "learn.ts").read_text(encoding="utf-8")
    block = re.search(r"CONTENT_TYPE_LABEL[^{]*\{([^}]*)\}", ts, re.S).group(1)
    keys = set(re.findall(r"^\s*([a-z_]+):", block, re.M))
    missing = set(OBJECT_TYPE_LABEL) - keys
    assert not missing, f"в web/src/lib/learn.ts нет меток для {sorted(missing)}"
    assert OBJECT_TYPE_LABEL["course_lesson"] == "Урок"
    assert course_index.LESSON_OBJECT_TYPE == "course_lesson"


def _doc(*nodes):
    # Контент урока хранится обёрткой `{"schema": 1, "doc": {...}}`.
    return {"schema": 1, "doc": {"type": "doc", "content": list(nodes)}}


def _video(mid, **attrs):
    return {"type": "video", "attrs": {"mediaId": mid, "src": None, **attrs}}


def test_collect_video_ids_lowercase_unique_in_order():
    a, b = uuid.uuid4(), uuid.uuid4()
    doc = _doc(
        _video(str(a).upper()),
        {"type": "paragraph", "content": [{"type": "text", "text": "x"}]},
        _video(str(b)),
        _video(str(a)),
        _video("not-a-uuid"),
        {"type": "figure", "attrs": {"mediaId": str(uuid.uuid4())}},
    )
    assert collect_video_ids(doc) == [str(a), str(b)]
    assert collect_video_ids(None) == []


def test_prepare_for_consumer_sets_track_and_status_only_when_given():
    a, b = uuid.uuid4(), uuid.uuid4()
    doc = _doc(_video(str(a)), _video(str(b)))
    sign = lambda mid: f"/api/media/{mid}?e=1&s=x"  # noqa: E731
    plain = prepare_for_consumer(doc, sign)
    assert "trackSrc" not in plain["doc"]["content"][0]["attrs"]
    assert "status" not in plain["doc"]["content"][0]["attrs"]
    out = prepare_for_consumer(
        doc,
        sign,
        track_urls={str(a): "/api/media/sub?e=1&s=y"},
        media_status={str(b): "processing"},
    )
    first, second = out["doc"]["content"][0]["attrs"], out["doc"]["content"][1]["attrs"]
    assert first["trackSrc"] == "/api/media/sub?e=1&s=y" and first["status"] == "ready"
    assert first["src"].startswith(f"/api/media/{a}")
    assert second["trackSrc"] is None and second["status"] == "processing"
    assert second["src"] is None
    # Исходный документ не изменён.
    assert "status" not in doc["doc"]["content"][0]["attrs"]


def test_lessons_referencing_media_sql_uses_jsonpath():
    stmt = course_index.lessons_referencing_media_stmt(uuid.uuid4())
    sql = str(stmt.compile(dialect=postgresql.dialect()))
    assert "jsonb_path_exists" in sql
    assert "$.** ? (@.mediaId == $id)" in sql
    assert "jsonb_build_object" in sql

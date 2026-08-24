"""Импортёр обязан ставить `requireFullWatch` на видео-ноды.

Импорт 2026-08-16 ключа не ставил, и в двух курсах 8 роликов оказались без
гейта вовсе: «обязательное» видео пролистывалось кнопкой «Урок пройден».
Ключ отсутствующий и ключ `false` — для сервера одно и то же
(`collect_required_videos`), поэтому проверяем именно наличие `True`.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.services.lesson_content import collect_required_videos
from tools.import_lms.build_bundle import Report, _lesson_nodes


def _row(kind: str, content: str = "") -> SimpleNamespace:
    return SimpleNamespace(kind=kind, content=content, image_md5=None, caption=None)


def test_video_node_requires_full_watch():
    url = "https://youtu.be/abc"
    nodes = _lesson_nodes([_row("Видео", url)], {f"yt:{url}": "v_1.mp4"}, Report())
    assert nodes == [
        {
            "type": "video",
            "attrs": {"mediaId": "@file:v_1.mp4", "requireFullWatch": True},
        }
    ]


def test_video_without_local_file_stays_a_link():
    nodes = _lesson_nodes([_row("Видео", "https://youtu.be/gone")], {}, Report())
    assert nodes[0]["type"] == "paragraph"


def test_video_course_lesson_requires_full_watch():
    # Второй эмитент — курс видеоинструкций; там урок целиком из одной ноды.
    from tools.import_lms import build_bundle as bb

    source = bb.__file__
    with open(source, encoding="utf-8") as fh:
        text = fh.read()
    # Обе ветки строят ноду в коде, а не через общий хелпер: сторожим, чтобы
    # флаг не потеряли ни в одной.
    assert text.count('"requireFullWatch": True') == 2


def test_flag_is_what_the_server_reads():
    media_id = "11111111-1111-1111-1111-111111111111"
    doc = {
        "schema": 1,
        "doc": {
            "type": "doc",
            "content": [
                {
                    "type": "video",
                    "attrs": {"mediaId": media_id, "requireFullWatch": True},
                }
            ],
        },
    }
    assert collect_required_videos(doc) == [media_id]

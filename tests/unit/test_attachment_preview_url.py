"""Подписанный адрес видео-вложения.

Тег `<video>` не шлёт `Authorization`, поэтому файл отдаётся по подписи без
JWT. Два свойства критичны и проверяются здесь, потому что оба ломаются молча:

1. **Адрес байт-в-байт стабилен внутри окна выдачи.** Список вложений
   перезапрашивается при каждом возврате на вкладку (`refetchOnWindowFocus:
   true`, `staleTime: 30_000` в `web/src/lib/queryClient.ts`). Менялся бы `src`
   — `<video>` перезагружался бы, а позиция воспроизведения слетала на 0. Ровно
   этот баг ловили на staging 25.08 на уроках, из-за него в `issue_token` и
   появилось округление `exp` по часовой сетке.
2. **Подпись привязана к КОНКРЕТНОМУ вложению.** Иначе ссылку, выданную на
   свой файл, можно предъявить чужому.
"""

from __future__ import annotations

from uuid import uuid4

from app.api.attachments import preview_url_for
from app.services.learn_media import verify_token


def test_only_video_gets_a_url() -> None:
    attachment_id = uuid4()
    assert preview_url_for(attachment_id, "video/mp4")
    assert preview_url_for(attachment_id, "video/quicktime")
    assert preview_url_for(attachment_id, "video/webm")
    # Картинкам и документам — нет: inline-показ image/* это отдельная задача,
    # и HEIC/HEIF из неё придётся исключать (браузеры их не декодируют).
    assert preview_url_for(attachment_id, "image/png") is None
    assert preview_url_for(attachment_id, "image/heic") is None
    assert preview_url_for(attachment_id, "application/pdf") is None


def test_url_is_byte_identical_on_repeat() -> None:
    attachment_id = uuid4()
    assert preview_url_for(attachment_id, "video/mp4") == preview_url_for(
        attachment_id, "video/mp4"
    )


def test_signature_does_not_transfer_between_attachments() -> None:
    mine, foreign = uuid4(), uuid4()
    url = preview_url_for(mine, "video/mp4")
    assert url is not None
    query = url.split("?", 1)[1]
    exp = int(dict(p.split("=", 1) for p in query.split("&"))["e"])
    sig = dict(p.split("=", 1) for p in query.split("&"))["s"]

    assert verify_token(f"attach:{mine}", exp, sig) is True
    assert verify_token(f"attach:{foreign}", exp, sig) is False
    # И в чужое пространство подписей (медиа уроков) она тоже не переносится.
    assert verify_token(str(mine), exp, sig) is False


def test_url_points_at_the_serving_route() -> None:
    attachment_id = uuid4()
    url = preview_url_for(attachment_id, "video/mp4")
    assert url is not None
    assert url.startswith(f"/api/attachments/{attachment_id}/file?e=")

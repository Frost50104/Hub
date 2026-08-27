"""Подпись адреса бейджа.

Главное свойство — БАЙТ-В-БАЙТ стабильный URL. `sign_media_path` его не даёт:
`issue_token` округляет `exp` по часовой сетке, то есть адрес меняется каждый
час. Для `<video>` это оправдано, для `<img>` бейджа — перекачка вместо 304 и
мигание пустого квадрата разом по всему списку проектов.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from app.services.learn_media import sign_immutable, sign_media_path
from app.services.project_badge import badge_url, verify_badge_signature


def _project(storage_key: str | None):
    return SimpleNamespace(id=uuid4(), badge_storage_key=storage_key)


def test_none_when_no_image() -> None:
    assert badge_url(_project(None)) is None


def test_url_is_byte_identical_on_repeat() -> None:
    """Регресс на подпись со сроком: она менялась бы по часовой сетке."""
    project = _project("t/projects/p/abc.png")
    assert badge_url(project) == badge_url(project)


def test_url_changes_with_storage_key() -> None:
    """Новая картинка = новый uuid в ключе = новый адрес и мёртвая старая подпись."""
    project = _project("t/projects/p/old.png")
    before = badge_url(project)
    project.badge_storage_key = "t/projects/p/new.png"
    assert badge_url(project) != before


def test_signature_verifies_and_rejects_wrong_key() -> None:
    project = _project("t/projects/p/abc.png")
    url = badge_url(project)
    assert url is not None
    sig = url.split("s=")[1]
    assert verify_badge_signature(project.id, "t/projects/p/abc.png", sig)
    # Тот же проект, другой файл — подпись не годится.
    assert not verify_badge_signature(project.id, "t/projects/p/other.png", sig)
    # Тот же файл, другой проект — тоже.
    assert not verify_badge_signature(uuid4(), "t/projects/p/abc.png", sig)


def test_media_signature_is_not_accepted_as_badge() -> None:
    """Пространства подписей разделены: `static:` против `{key}:{exp}`."""
    media_id = uuid4()
    media_sig = sign_media_path(media_id).split("s=")[1]
    assert not verify_badge_signature(media_id, str(media_id), media_sig)


def test_immutable_namespace_is_isolated_from_bare_key() -> None:
    project_id = uuid4()
    key = "t/projects/p/abc.png"
    # Подпись «голого» ключа не должна годиться для бейджа: у бейджа своё
    # пространство `projectbadge:{id}:{key}`.
    assert not verify_badge_signature(project_id, key, sign_immutable(key))

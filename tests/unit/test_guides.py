"""Инструкции: кому какая и почему ссылка подписана.

Внутри инструкции — реальные экраны с ФИО коллег и адресами точек, поэтому
файл не лежит публичной статикой: ссылка подписана той же машинерией, что
медиа уроков, но с ДРУГИМ ключом сообщения.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from app.services import learn_media as lm
from app.services.guides import (
    GUIDE_FILES,
    guides_for_role,
    verify_guide_signature,
)
from app.services.learn_media import sign_media_path, verify_media_signature


def _parse(url: str) -> tuple[str, int, str]:
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    return parsed.path.rsplit("/", 1)[-1], int(qs["e"][0]), qs["s"][0]


class TestWhoGetsWhat:
    def test_admin_sees_both_own_first(self):
        rows = guides_for_role("admin")
        assert [r.kind for r in rows] == ["admin", "employee"]

    def test_everyone_else_sees_only_employee(self):
        for role in ("member", "viewer"):
            assert [r.kind for r in guides_for_role(role)] == ["employee"]

    def test_no_hub_role_no_guides(self):
        # Юзер другого продукта Signaris Hub вообще не видит.
        assert guides_for_role(None) == []

    def test_every_kind_has_a_file(self):
        for row in guides_for_role("admin"):
            assert row.kind in GUIDE_FILES


class TestSignature:
    def test_roundtrip(self):
        kind, exp, sig = _parse(guides_for_role("admin")[0].url)
        assert verify_guide_signature(kind, exp, sig)

    def test_tampered_kind_is_rejected(self):
        """Главное: подпись на сотрудницкую нельзя предъявить админской."""
        _kind, exp, sig = _parse(guides_for_role("member")[0].url)
        assert not verify_guide_signature("admin", exp, sig)

    def test_unknown_kind_is_rejected(self):
        _kind, exp, sig = _parse(guides_for_role("member")[0].url)
        assert not verify_guide_signature("../../etc/passwd", exp, sig)

    def test_expired(self, monkeypatch):
        kind, exp, sig = _parse(guides_for_role("member")[0].url)
        monkeypatch.setattr(lm.time, "time", lambda: exp + 1)
        assert not verify_guide_signature(kind, exp, sig)

    def test_media_signature_is_not_a_guide_signature(self):
        # Ключи сообщений разные (`{media_id}` против `guide:{kind}`) — иначе
        # подписанная ссылка на медиа открывала бы инструкцию.
        media_id = uuid4()
        _name, exp, sig = _parse(sign_media_path(media_id))
        assert verify_media_signature(media_id, exp, sig)
        assert not verify_guide_signature("employee", exp, sig)

    def test_url_is_stable_within_the_bucket(self, monkeypatch):
        # Инструкция весит мегабайты: «новый URL на каждый ответ /me» означал
        # бы перекачку вместо 304.
        base = 1_800_000_000  # кратно часу
        monkeypatch.setattr(lm.time, "time", lambda: base + 5)
        first = guides_for_role("member")[0].url
        monkeypatch.setattr(lm.time, "time", lambda: base + 1799)
        assert guides_for_role("member")[0].url == first

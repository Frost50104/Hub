"""VAPID-ключ: транспорт пуша, который месяц никто не проверял.

Инцидент 26.08: web push не доставлялся с 29 июля — `push_sender` отдавал
pywebpush СОДЕРЖИМОЕ PEM-файла, а тот в этом случае зовёт
`py_vapid.Vapid.from_string`, который PEM с заголовками не понимает (срезает
переводы строк, гонит текст через base64url и отдаёт в `from_der`). Каждая
отправка падала с «ASN.1 parsing error», ошибка тонула в warning фоновой
задачи, и ни один тест её не ловил: все интеграционные наборы мокают отправку
целиком.

Поэтому тесты здесь работают с НАСТОЯЩИМ ключом и НАСТОЯЩЕЙ подписью — без
сети, но и без моков на пути ключа.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
)
from py_vapid import Vapid01

from app.config import get_settings
from app.services import push_sender

APPLE = "https://web.push.apple.com/QHT-JWQuGN5_7BqJVO"
FCM = "https://fcm.googleapis.com/fcm/send/cAQZRdZiK"


@pytest.fixture
def vapid_key(tmp_path: Path, monkeypatch) -> Path:
    """Свежая пара ключей в PEM — ровно того же вида, что пишет
    `scripts/generate_vapid.py` (TraditionalOpenSSL = SEC1 «EC PRIVATE KEY»)."""
    priv = ec.generate_private_key(ec.SECP256R1())
    path = tmp_path / "vapid_private.pem"
    path.write_bytes(
        priv.private_bytes(Encoding.PEM, PrivateFormat.TraditionalOpenSSL, NoEncryption())
    )
    monkeypatch.setattr(get_settings(), "vapid_private_key_path", path)
    push_sender.reset_vapid_cache()
    return path


def test_key_loads_from_pem(vapid_key: Path):
    """Тот самый регресс: PEM с заголовками обязан загружаться."""
    assert push_sender.load_vapid() is not None


def test_loader_returns_vapid_object_not_text(vapid_key: Path):
    """Строку pywebpush уводит в `from_string`, а он PEM не понимает.

    Проверяем именно ТИП: вернись отсюда текст ключа — отправка снова начала бы
    падать на каждой попытке, и снова молча.
    """
    vapid = push_sender.load_vapid()
    assert isinstance(vapid, Vapid01)


def test_key_signs_a_real_vapid_header(vapid_key: Path):
    """Ключ не просто читается, но и годится для подписи заголовка."""
    vapid = push_sender.load_vapid()
    assert vapid is not None
    headers = vapid.sign(
        {"sub": "mailto:ops@signaris.ru", "aud": "https://web.push.apple.com"}
    )
    # Vapid draft-02: подпись и ключ едут одним заголовком.
    assert headers["Authorization"].startswith("vapid ")
    assert "k=" in headers["Authorization"]


def test_missing_key_file_does_not_silently_generate_a_new_one(
    tmp_path: Path, monkeypatch
):
    """Пропавший ключ — громкая ошибка, а не тихая ротация.

    `py_vapid.Vapid.from_file` при отсутствии файла ГЕНЕРИРУЕТ новую пару и
    записывает её на диск. Публичный ключ в env при этом остаётся прежним, все
    выданные подписки становятся мусором, а отправка выглядит успешной. Поэтому
    существование файла проверяется до вызова библиотеки.
    """
    missing = tmp_path / "nope.pem"
    monkeypatch.setattr(get_settings(), "vapid_private_key_path", missing)
    push_sender.reset_vapid_cache()
    assert push_sender.load_vapid() is None
    assert not missing.exists(), "ключ не должен создаваться на пустом месте"


def test_broken_key_file_is_not_a_crash(tmp_path: Path, monkeypatch):
    path = tmp_path / "broken.pem"
    path.write_text("-----BEGIN EC PRIVATE KEY-----\nnot a key\n-----END EC PRIVATE KEY-----\n")
    monkeypatch.setattr(get_settings(), "vapid_private_key_path", path)
    push_sender.reset_vapid_cache()
    assert push_sender.load_vapid() is None


def test_claims_are_not_shared_between_subscriptions(vapid_key: Path, monkeypatch):
    """`aud` одной подписки не должен утечь в другую.

    pywebpush дописывает `aud` и `exp` в ПЕРЕДАННЫЙ словарь (в его исходниках
    об этом даже есть комментарий «passed structures are mutable in python»).
    Один общий словарь на Apple и FCM подписал бы вторую подписку адресом
    первой — и транспорт отверг бы её.
    """
    seen: list[dict] = []

    def _fake_webpush(**kwargs):
        claims = kwargs["vapid_claims"]
        # Имитируем ровно то, что делает pywebpush со словарём.
        claims.setdefault("aud", kwargs["subscription_info"]["endpoint"].split("/")[2])
        seen.append(claims)

        class _R:
            status_code = 201

        return _R()

    monkeypatch.setattr(push_sender, "webpush", _fake_webpush)
    vapid = push_sender.load_vapid()
    for endpoint in (APPLE, FCM):
        push_sender._send_blocking(
            endpoint=endpoint,
            p256dh="p",
            auth="a",
            payload={"title": "t"},
            vapid=vapid,
            vapid_subject="mailto:ops@signaris.ru",
        )

    assert len(seen) == 2
    assert seen[0] is not seen[1], "словарь claims переиспользован между подписками"
    assert seen[0]["aud"] != seen[1]["aud"]


def test_public_key_mismatch_disables_push(vapid_key: Path, monkeypatch):
    """Приватный ключ не от того публичного — слать бессмысленно.

    Браузер подписался под ключ из `/api/env`; подпись другой парой он не
    примет. Молча слать в никуда хуже, чем выключить пуш и написать ERROR.
    """
    monkeypatch.setattr(get_settings(), "vapid_public_key", "BBBB-not-our-key")
    push_sender.reset_vapid_cache()
    assert push_sender.load_vapid() is None


def test_public_key_match_is_padding_insensitive(vapid_key: Path, monkeypatch):
    """base64url публичного ключа сравнивается без хвостовых '='.

    `scripts/generate_vapid.py` печатает ключ без padding, но в .env он мог
    попасть и с ним — придираться к этому нельзя.
    """
    vapid = push_sender.load_vapid()
    assert vapid is not None
    monkeypatch.setattr(
        get_settings(), "vapid_public_key", push_sender._public_b64(vapid) + "=="
    )
    push_sender.reset_vapid_cache()
    assert push_sender.load_vapid() is not None

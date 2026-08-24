"""Юнит-тесты learn_media: подписи URL + faststart-парсер mp4."""

from __future__ import annotations

import struct
import time
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from app.config import get_settings
from app.services import learn_media as lm
from app.services.learn_media import (
    media_size_limit,
    mp4_duration_seconds,
    mp4_has_faststart,
    sign_media_path,
    storage_key_for_media,
    verify_media_signature,
)


def _parse_signed(url: str) -> tuple[int, str]:
    qs = parse_qs(urlparse(url).query)
    return int(qs["e"][0]), qs["s"][0]


class TestSignedUrls:
    def test_roundtrip(self):
        media_id = uuid4()
        url = sign_media_path(media_id)
        exp, sig = _parse_signed(url)
        assert url.startswith(f"/api/media/{media_id}?")
        assert verify_media_signature(media_id, exp, sig)

    def test_expired(self):
        media_id = uuid4()
        url = sign_media_path(media_id, ttl_sec=-10)
        exp, sig = _parse_signed(url)
        assert exp < time.time()
        assert not verify_media_signature(media_id, exp, sig)

    def test_tampered_signature(self):
        media_id = uuid4()
        exp, sig = _parse_signed(sign_media_path(media_id))
        bad = ("0" if sig[0] != "0" else "1") + sig[1:]
        assert not verify_media_signature(media_id, exp, bad)

    def test_tampered_expiry(self):
        media_id = uuid4()
        exp, sig = _parse_signed(sign_media_path(media_id))
        assert not verify_media_signature(media_id, exp + 3600, sig)

    def test_wrong_media_id(self):
        media_id = uuid4()
        exp, sig = _parse_signed(sign_media_path(media_id))
        assert not verify_media_signature(uuid4(), exp, sig)

    def test_same_file_same_url_within_the_bucket(self, monkeypatch):
        """Повторный ответ ручки обязан отдать ТОТ ЖЕ URL.

        Прежний `now + ttl` менялся каждую секунду: рефетч урока подставлял
        `<video>` новый `src`, браузер перезагружал элемент — позиция слетала
        на 0 и воспроизведение вставало на паузу (staging, 25.08).
        """
        media_id = uuid4()
        base = 1_800_000_000  # кратно часу
        monkeypatch.setattr(lm.time, "time", lambda: base + 5)
        first = sign_media_path(media_id)
        monkeypatch.setattr(lm.time, "time", lambda: base + 1799)
        assert sign_media_path(media_id) == first

    def test_next_bucket_reissues_and_stays_valid(self, monkeypatch):
        media_id = uuid4()
        base = 1_800_000_000
        monkeypatch.setattr(lm.time, "time", lambda: base + 5)
        first = sign_media_path(media_id)
        monkeypatch.setattr(lm.time, "time", lambda: base + 3605)
        second = sign_media_path(media_id)
        assert second != first
        exp, sig = _parse_signed(second)
        assert verify_media_signature(media_id, exp, sig)

    def test_remaining_life_never_below_half_ttl(self, monkeypatch):
        # Округление вниз укорачивает жизнь ссылки — но не настолько, чтобы
        # видео обрывалось на середине просмотра.
        ttl = get_settings().media_url_ttl_sec
        media_id = uuid4()
        base = 1_800_000_000
        for offset in (0, 1, 1800, 3599):
            now = base + offset
            monkeypatch.setattr(lm.time, "time", lambda now=now: now)
            exp, _sig = _parse_signed(sign_media_path(media_id))
            assert exp - now >= ttl / 2


def _box(box_type: bytes, payload: bytes = b"") -> bytes:
    return struct.pack(">I", 8 + len(payload)) + box_type + payload


class TestFaststart:
    def test_moov_before_mdat(self, tmp_path):
        f = tmp_path / "a.mp4"
        f.write_bytes(_box(b"ftyp", b"isom\x00\x00\x00\x00") + _box(b"moov") + _box(b"mdat"))
        assert mp4_has_faststart(f)

    def test_mdat_before_moov(self, tmp_path):
        f = tmp_path / "b.mp4"
        f.write_bytes(_box(b"ftyp", b"isom\x00\x00\x00\x00") + _box(b"mdat") + _box(b"moov"))
        assert not mp4_has_faststart(f)

    def test_64bit_size_box(self, tmp_path):
        # size==1 → расширенный 64-битный размер в следующих 8 байтах.
        big = struct.pack(">I", 1) + b"free" + struct.pack(">Q", 16)
        f = tmp_path / "c.mp4"
        f.write_bytes(_box(b"ftyp") + big + _box(b"moov"))
        assert mp4_has_faststart(f)

    def test_garbage_fail_closed(self, tmp_path):
        f = tmp_path / "d.mp4"
        f.write_bytes(b"definitely not an mp4 file at all")
        assert not mp4_has_faststart(f)

    def test_empty_file(self, tmp_path):
        f = tmp_path / "e.mp4"
        f.write_bytes(b"")
        assert not mp4_has_faststart(f)

    def test_missing_file(self, tmp_path):
        assert not mp4_has_faststart(tmp_path / "nope.mp4")

    def test_truncated_header(self, tmp_path):
        f = tmp_path / "f.mp4"
        f.write_bytes(b"\x00\x00")
        assert not mp4_has_faststart(f)

    def test_zero_size_box(self, tmp_path):
        # size==0 = «до конца файла» без moov — False.
        f = tmp_path / "g.mp4"
        f.write_bytes(struct.pack(">I", 0) + b"free" + b"\x00" * 16)
        assert not mp4_has_faststart(f)


class TestStorageAndLimits:
    def test_storage_key_layout(self):
        tenant, media = uuid4(), uuid4()
        key, sanitized = storage_key_for_media(tenant, media, "Видео урока.mp4")
        assert key.startswith(f"{tenant}/learn/media/{media}-")
        assert key.endswith(sanitized)

    def test_size_limits_by_kind(self):
        assert media_size_limit("video", {}) == 300 * 1024 * 1024
        assert media_size_limit("pdf", {}) == 50 * 1024 * 1024
        assert media_size_limit("image", {}) == 10 * 1024 * 1024
        assert media_size_limit("video", {"video_max_bytes": 100}) == 100


def _mvhd(*, version: int, timescale: int, duration: int) -> bytes:
    """mvhd-бокс. v0 — 32-битные creation/modification/duration, v1 — 64-битные."""
    if version == 1:
        payload = bytes([1, 0, 0, 0]) + struct.pack(">QQIQ", 0, 0, timescale, duration)
    else:
        payload = bytes([0, 0, 0, 0]) + struct.pack(">IIII", 0, 0, timescale, duration)
    return _box(b"mvhd", payload)


class TestMp4Duration:
    """Длительность нужна серверу: гейт делит просмотренное на неё, и клиентское
    число может как открыть гейт раньше времени, так и навсегда заблокировать
    завершение (завышение в 1,12 раза уже делает 90% недостижимыми)."""

    def test_v0(self, tmp_path):
        f = tmp_path / "v0.mp4"
        f.write_bytes(
            _box(b"ftyp", b"isom")
            + _box(b"moov", _mvhd(version=0, timescale=1000, duration=53_243))
            + _box(b"mdat")
        )
        assert mp4_duration_seconds(f) == 53.243

    def test_v1_64bit(self, tmp_path):
        f = tmp_path / "v1.mp4"
        f.write_bytes(
            _box(b"ftyp", b"isom")
            + _box(b"moov", _mvhd(version=1, timescale=600, duration=31_946))
            + _box(b"mdat")
        )
        got = mp4_duration_seconds(f)
        assert got is not None and abs(got - 53.2433) < 0.001

    def test_mvhd_not_first_in_moov(self, tmp_path):
        # Реальные файлы кладут перед mvhd другие боксы (например, udta).
        f = tmp_path / "nested.mp4"
        moov = _box(b"udta", b"\x00" * 16) + _mvhd(version=0, timescale=90_000, duration=450_000)
        f.write_bytes(_box(b"ftyp", b"isom") + _box(b"moov", moov))
        assert mp4_duration_seconds(f) == 5.0

    def test_no_moov(self, tmp_path):
        f = tmp_path / "nomoov.mp4"
        f.write_bytes(_box(b"ftyp", b"isom") + _box(b"mdat"))
        assert mp4_duration_seconds(f) is None

    def test_moov_without_mvhd(self, tmp_path):
        f = tmp_path / "nomvhd.mp4"
        f.write_bytes(_box(b"ftyp", b"isom") + _box(b"moov", _box(b"trak")))
        assert mp4_duration_seconds(f) is None

    def test_truncated_mvhd(self, tmp_path):
        f = tmp_path / "cut.mp4"
        full = _box(b"ftyp", b"isom") + _box(
            b"moov", _mvhd(version=0, timescale=1000, duration=53_243)
        )
        f.write_bytes(full[:-6])
        assert mp4_duration_seconds(f) is None

    def test_zero_timescale(self, tmp_path):
        f = tmp_path / "zero.mp4"
        f.write_bytes(
            _box(b"ftyp", b"isom")
            + _box(b"moov", _mvhd(version=0, timescale=0, duration=1000))
        )
        assert mp4_duration_seconds(f) is None

    def test_absurd_duration_rejected(self, tmp_path):
        # Разъехавшийся timescale даёт годы — это не учебный ролик.
        f = tmp_path / "absurd.mp4"
        f.write_bytes(
            _box(b"ftyp", b"isom")
            + _box(b"moov", _mvhd(version=0, timescale=1, duration=90_000))
        )
        assert mp4_duration_seconds(f) is None

    def test_garbage(self, tmp_path):
        f = tmp_path / "garbage.mp4"
        f.write_bytes(b"definitely not an mp4 file at all")
        assert mp4_duration_seconds(f) is None

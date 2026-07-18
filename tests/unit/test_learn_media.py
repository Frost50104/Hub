"""Юнит-тесты learn_media: подписи URL + faststart-парсер mp4."""

from __future__ import annotations

import struct
import time
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from app.services.learn_media import (
    media_size_limit,
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

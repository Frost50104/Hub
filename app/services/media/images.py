"""Размер картинки без Pillow: сцена гуся обязана быть 16:9 (`±5 %`), а
`media_files` ширину и высоту не хранит. Разбираем заголовки PNG, JPEG и WebP
руками; незнакомый формат → None, и проверка соотношения пропускается.
"""

from __future__ import annotations

import struct
from pathlib import Path

_HEAD = 64 * 1024


def image_size(data: bytes) -> tuple[int, int] | None:
    """(ширина, высота) по первым байтам файла или None."""
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24 and data[12:16] == b"IHDR":
        w, h = struct.unpack(">II", data[16:24])
        return (w, h) if w and h else None
    if data[:12][:4] == b"RIFF" and data[8:12] == b"WEBP":
        return _webp_size(data)
    if data[:2] == b"\xff\xd8":
        return _jpeg_size(data)
    return None


def image_size_of(path: Path) -> tuple[int, int] | None:
    with path.open("rb") as fh:
        return image_size(fh.read(_HEAD))


def _jpeg_size(data: bytes) -> tuple[int, int] | None:
    i = 2
    n = len(data)
    while i + 9 <= n:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        if i + 4 > n:
            return None
        seg_len = struct.unpack(">H", data[i + 2 : i + 4])[0]
        # SOF0..SOF15 кроме DHT/JPG/DAC — кадр с размерами.
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            if i + 9 > n:
                return None
            h, w = struct.unpack(">HH", data[i + 5 : i + 9])
            return (w, h) if w and h else None
        i += 2 + seg_len
    return None


def _webp_size(data: bytes) -> tuple[int, int] | None:
    chunk = data[12:16]
    if chunk == b"VP8X" and len(data) >= 30:
        w = 1 + int.from_bytes(data[24:27], "little")
        h = 1 + int.from_bytes(data[27:30], "little")
        return (w, h)
    if chunk == b"VP8L" and len(data) >= 25:
        b = data[21:25]
        w = 1 + (((b[1] & 0x3F) << 8) | b[0])
        h = 1 + (((b[3] & 0x0F) << 10) | (b[2] << 2) | ((b[1] & 0xC0) >> 6))
        return (w, h)
    if chunk == b"VP8 " and len(data) >= 30:
        w = struct.unpack("<H", data[26:28])[0] & 0x3FFF
        h = struct.unpack("<H", data[28:30])[0] & 0x3FFF
        return (w, h) if w and h else None
    return None


def aspect_ok(size: tuple[int, int], *, ratio: float = 16 / 9, tolerance: float = 0.05) -> bool:
    w, h = size
    return h > 0 and abs(w / h - ratio) <= ratio * tolerance

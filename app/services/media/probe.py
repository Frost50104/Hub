"""Паспорт медиафайла из `ffprobe -print_format json`. Разбор чистый —
тесты идут по сохранённым JSON-образцам без бинаря."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Any


@dataclass(frozen=True)
class Probe:
    duration: float
    width: int | None
    height: int | None
    fps: float | None
    vcodec: str | None
    acodec: str | None
    pix_fmt: str | None
    rotation: int
    has_audio: bool
    container: str
    size_bytes: int | None

    @property
    def has_video(self) -> bool:
        return self.vcodec is not None

    @property
    def display_size(self) -> tuple[int, int] | None:
        """Размер с учётом поворота (телефонный MOV хранит кадр лёжа)."""
        if self.width is None or self.height is None:
            return None
        if self.rotation % 180 == 90:
            return (self.height, self.width)
        return (self.width, self.height)


def _fps(raw: str | None) -> float | None:
    if not raw or raw in ("0/0", "0"):
        return None
    try:
        value = float(Fraction(raw))
    except (ValueError, ZeroDivisionError):
        return None
    return round(value, 3) if value > 0 else None


def _rotation(stream: dict[str, Any]) -> int:
    rot = 0
    for sd in stream.get("side_data_list") or []:
        if "rotation" in sd:
            try:
                rot = int(round(float(sd["rotation"])))
            except (TypeError, ValueError):
                rot = 0
    tags = stream.get("tags") or {}
    if not rot and tags.get("rotate"):
        try:
            rot = int(float(tags["rotate"]))
        except (TypeError, ValueError):
            rot = 0
    return rot % 360


def _container(fmt: dict[str, Any]) -> str:
    name = str(fmt.get("format_name") or "")
    if "webm" in name or "matroska" in name:
        return "webm"
    if "mp4" in name or "mov" in name:
        return "mp4"
    if "wav" in name:
        return "wav"
    return name.split(",")[0] or "unknown"


def parse_ffprobe(data: dict[str, Any]) -> Probe:
    fmt = data.get("format") or {}
    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    duration = 0.0
    for src in (fmt, video, audio):
        if src and src.get("duration"):
            try:
                duration = float(src["duration"])
                break
            except (TypeError, ValueError):
                continue
    size = None
    if fmt.get("size"):
        try:
            size = int(fmt["size"])
        except (TypeError, ValueError):
            size = None
    return Probe(
        duration=duration,
        width=int(video["width"]) if video and video.get("width") else None,
        height=int(video["height"]) if video and video.get("height") else None,
        fps=_fps(video.get("avg_frame_rate") or video.get("r_frame_rate")) if video else None,
        vcodec=video.get("codec_name") if video else None,
        acodec=audio.get("codec_name") if audio else None,
        pix_fmt=video.get("pix_fmt") if video else None,
        rotation=_rotation(video) if video else 0,
        has_audio=audio is not None,
        container=_container(fmt),
        size_bytes=size,
    )

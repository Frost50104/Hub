"""Нормализация загрузки к «MP4 H.264/AAC yuv420p, faststart»: ремукс без
перекодирования, когда можно (`copy`), иначе перекодирование с потолками fps и
высоты. Чистые функции над `Probe` → аргументы ffmpeg."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from app.services.media.probe import Probe

Mode = Literal["copy", "transcode"]

X264 = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p"]
AAC = ["-c:a", "aac", "-b:a", "128k", "-ac", "2", "-ar", "48000"]
FASTSTART = ["-movflags", "+faststart"]


def plan(probe: Probe, *, fps_cap: float = 30.0, scale_cap: int = 1080) -> Mode:
    """`copy`, если и так MP4/MOV с H.264 yuv420p (+AAC или без звука), в
    пределах потолков и без поворота — тогда достаточно ремукса с faststart."""
    if probe.container != "mp4" or probe.vcodec != "h264" or probe.pix_fmt != "yuv420p":
        return "transcode"
    if probe.acodec not in (None, "aac"):
        return "transcode"
    if probe.rotation % 360 != 0:
        return "transcode"
    if probe.height is not None and probe.height > scale_cap:
        return "transcode"
    if probe.fps is not None and probe.fps > fps_cap + 0.01:
        return "transcode"
    return "copy"


def target_fps(probe: Probe, *, fps_cap: float = 30.0) -> float:
    return min(probe.fps or fps_cap, fps_cap)


def video_filter(probe: Probe, *, fps_cap: float = 30.0, scale_cap: int = 1080) -> str:
    """`scale` по потолку высоты (чётные размеры), `fps`, `format` — для
    transcode-нормализации и для частей сборки."""
    fps = target_fps(probe, fps_cap=fps_cap)
    return f"scale=-2:'min(ih,{scale_cap})':flags=bicubic,fps={fps:g},format=yuv420p"


def args(
    mode: Mode,
    src: Path,
    dst: Path,
    probe: Probe,
    *,
    fps_cap: float = 30.0,
    scale_cap: int = 1080,
    threads: int = 1,
) -> list[str]:
    """Аргументы ffmpeg после бинаря и глобальных флагов (`-y`, `-nostdin`…)."""
    if mode == "copy":
        out = ["-i", str(src), "-map", "0:v:0", "-map", "0:a:0?", "-c", "copy", *FASTSTART]
        return [*out, str(dst)]
    out = ["-i", str(src), "-map", "0:v:0", "-map", "0:a:0?"]
    out += ["-vf", video_filter(probe, fps_cap=fps_cap, scale_cap=scale_cap)]
    out += [*X264, "-threads", str(threads)]
    if probe.has_audio:
        out += AAC
    return [*out, *FASTSTART, str(dst)]

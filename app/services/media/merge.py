"""Сборка одного видео из нескольких записей (`merge`): целевой формат,
режим части (ремукс / перекодирование), аргументы ffmpeg, список для
`concat`. Чистые функции над `Probe`; бинарь зовёт `merge_job`.

Правила (решение владельца 22.10): целевая высота — лучшая среди частей с
потолком `scale_cap`, кадр 16:9 (другое соотношение — letterbox), fps — лучший
с потолком `fps_cap`, звук 48 кГц стерео AAC; часть без звука получает тишину;
подрезка «с … до …» — перекодированием (точность до кадра). Часть, уже
совпадающая с целью, идёт `-c copy` — у OBS один профиль на все записи.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.services.media.normalize import AAC, FASTSTART, X264
from app.services.media.probe import Probe

Mode = Literal["copy", "transcode"]
AUDIO_RATE = 48000
AUDIO_CHANNELS = 2


@dataclass(frozen=True)
class Target:
    width: int
    height: int
    fps: float


def _even(value: float) -> int:
    n = int(round(value))
    return n if n % 2 == 0 else n + 1


def plan_target(probes: list[Probe], *, fps_cap: float = 30.0, scale_cap: int = 1080) -> Target:
    heights = [size[1] for p in probes if (size := p.display_size) is not None]
    if not heights:
        raise ValueError("ни у одной части нет видеодорожки")
    height = _even(min(max(heights), scale_cap))
    width = _even(height * 16 / 9)
    fps_values = [p.fps for p in probes if p.fps]
    fps = min(max(fps_values) if fps_values else fps_cap, fps_cap)
    return Target(width=width, height=height, fps=round(fps, 3))


def part_duration(probe: Probe, *, trim_start: float = 0.0, trim_end: float | None = None) -> float:
    end = probe.duration if trim_end is None else min(float(trim_end), probe.duration)
    return max(0.0, end - max(0.0, float(trim_start)))


def part_mode(
    probe: Probe, target: Target, *, trim_start: float = 0.0, trim_end: float | None = None
) -> Mode:
    """`copy`, если часть без подрезки и ровно в целевом формате (контейнер,
    кодеки, размер, fps, звук 48 кГц стерео) — иначе `concat -c copy` склеит
    несовместимые потоки в битый файл."""
    if trim_start > 0 or trim_end is not None:
        return "transcode"
    if probe.container != "mp4" or probe.vcodec != "h264" or probe.pix_fmt != "yuv420p":
        return "transcode"
    if probe.rotation % 360 != 0 or probe.display_size != (target.width, target.height):
        return "transcode"
    if probe.fps is None or abs(probe.fps - target.fps) > 0.01:
        return "transcode"
    if not probe.has_audio or probe.acodec != "aac":
        return "transcode"
    if probe.sample_rate != AUDIO_RATE or probe.channels != AUDIO_CHANNELS:
        return "transcode"
    return "copy"


def video_filter(target: Target) -> str:
    w, h = target.width, target.height
    return (
        f"scale={w}:{h}:force_original_aspect_ratio=decrease:flags=bicubic,"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={target.fps:g},format=yuv420p"
    )


def part_args(
    src: Path,
    dst: Path,
    probe: Probe,
    target: Target,
    *,
    mode: Mode,
    trim_start: float = 0.0,
    trim_end: float | None = None,
    threads: int = 1,
) -> list[str]:
    """Аргументы ffmpeg для промежуточного файла части (после глобальных флагов)."""
    if mode == "copy":
        return ["-i", str(src), "-map", "0:v:0", "-map", "0:a:0", "-c", "copy", str(dst)]
    out: list[str] = []
    if trim_start > 0:
        # `-ss` ДО `-i`: быстрый поиск по ключевым кадрам, а точность даёт
        # перекодирование — лишние кадры до точки среза декодер отбрасывает.
        out += ["-ss", f"{trim_start:.3f}"]
    out += ["-i", str(src)]
    if not probe.has_audio:
        out += ["-f", "lavfi", "-i", f"anullsrc=r={AUDIO_RATE}:cl=stereo"]
    duration = part_duration(probe, trim_start=trim_start, trim_end=trim_end)
    if trim_end is not None or not probe.has_audio:
        # Длительность выхода: при подрезке — до «до», при тишине — иначе
        # бесконечный anullsrc не даст ffmpeg закончить.
        out += ["-t", f"{duration:.3f}"]
    out += ["-map", "0:v:0", "-map", "0:a:0" if probe.has_audio else "1:a:0"]
    out += ["-vf", video_filter(target), *X264, "-threads", str(threads), *AAC, str(dst)]
    return out


def concat_list(paths: list[Path]) -> str:
    """Текст для `-f concat -safe 0`: абсолютные пути, апостроф экранируется."""
    lines = []
    for p in paths:
        quoted = str(p).replace("'", "'\\''")
        lines.append(f"file '{quoted}'")
    return "\n".join(lines) + "\n"


def concat_args(list_path: Path, dst: Path) -> list[str]:
    return [
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_path),
        "-c",
        "copy",
        *FASTSTART,
        str(dst),
    ]

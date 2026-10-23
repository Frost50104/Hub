"""Поиск лица в кадрах раскадровки — ОБНАРУЖЕНИЕ любого человека, не
распознавание (решение владельца 22.10). OpenCV импортируется лениво и только
в медиа-воркере: в API-процесс `cv2` попадать не должен (сторож в
`tests/unit/test_media_faces.py`). Чистые части (агрегация, разбор сцен) —
без OpenCV."""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

_SHOWINFO_PTS = re.compile(r"pts_time:\s*([0-9.]+)")


def face_ratio(faces: Iterable[tuple[int, int, int, int]], frame_height: int) -> float:
    """Доля высоты кадра под самым большим лицом; 0 — лиц нет."""
    if frame_height <= 0:
        return 0.0
    best = 0
    for _x, _y, _w, h in faces:
        best = max(best, int(h))
    return round(best / frame_height, 4)


def parse_scene_cuts(stderr: str) -> list[float]:
    """`select='gt(scene,T)',showinfo` печатает кадр на каждую смену сцены —
    берём `pts_time`."""
    return [float(m.group(1)) for m in _SHOWINFO_PTS.finditer(stderr)]


def scene_cut_args(src: Path, *, threshold: float = 0.4) -> list[str]:
    return [
        "-i",
        str(src),
        "-vf",
        f"select='gt(scene,{threshold:g})',showinfo",
        "-an",
        "-f",
        "null",
        "-",
    ]


def frames_args(src: Path, out_dir: Path, *, width: int = 320) -> list[str]:
    """Кадр в секунду, узкий JPEG — хватает каскаду, не хватает памяти, чтобы
    распухнуть: часовой вебинар — 3600 файлов по ~15 КБ."""
    return [
        "-i",
        str(src),
        "-vf",
        f"fps=1,scale={width}:-2",
        "-q:v",
        "6",
        "-an",
        str(out_dir / "f-%06d.jpg"),
    ]


class FaceDetector:
    """Haar-каскады из комплекта OpenCV (frontal + profile): без внешних файлов,
    ~10 мс на кадр 320 px на двух ядрах VPS."""

    def __init__(self) -> None:
        import cv2  # noqa: PLC0415 — только в воркере

        self._cv2 = cv2
        base = cv2.data.haarcascades
        self._frontal = cv2.CascadeClassifier(base + "haarcascade_frontalface_default.xml")
        self._profile = cv2.CascadeClassifier(base + "haarcascade_profileface.xml")
        if self._frontal.empty() or self._profile.empty():
            raise RuntimeError("каскады OpenCV не загрузились")

    def ratio_for_file(self, path: Path) -> float:
        cv2 = self._cv2
        img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if img is None:
            return 0.0
        h = int(img.shape[0])
        min_size = (max(20, h // 12), max(20, h // 12))
        faces: list[Any] = list(
            self._frontal.detectMultiScale(img, scaleFactor=1.1, minNeighbors=4, minSize=min_size)
        )
        if not faces:
            faces = list(
                self._profile.detectMultiScale(
                    img, scaleFactor=1.1, minNeighbors=4, minSize=min_size
                )
            )
        return face_ratio([tuple(int(v) for v in f) for f in faces], h)


def ratios_for_frames(frames: list[Path], detector: FaceDetector) -> list[float]:
    """Ряд «доля кадра под лицом» по секундам; файлы удаляются по мере чтения."""
    out: list[float] = []
    for frame in frames:
        try:
            out.append(detector.ratio_for_file(frame))
        finally:
            frame.unlink(missing_ok=True)
    return out

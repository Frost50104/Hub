"""Раскадровка: чистые части (доля лица, смены сцен, аргументы ffmpeg) и
сторож — OpenCV не попадает в API-процесс."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from app.services.media import faces


def test_api_process_never_imports_opencv():
    """Отдельный интерпретатор: в общем прогоне cv2 уже импортирован тестами
    раскадровки, и проверка по `sys.modules` текущего процесса врала бы."""
    code = "import sys, app.main; assert 'cv2' not in sys.modules, 'cv2 в API-процессе'"
    proc = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=120, check=False
    )
    assert proc.returncode == 0, proc.stderr[-600:]


def test_face_ratio_takes_the_largest_face():
    assert faces.face_ratio([], 240) == 0.0
    assert faces.face_ratio([(0, 0, 20, 30), (0, 0, 50, 60)], 240) == 0.25
    assert faces.face_ratio([(0, 0, 20, 30)], 0) == 0.0


def test_parse_scene_cuts_and_args():
    log = (
        "[Parsed_showinfo_1 @ 0x1] n:   0 pts:  12345 pts_time:12.345 ...\n"
        "[Parsed_showinfo_1 @ 0x1] n:   1 pts:  99999 pts_time:99.9 ...\n"
        "frame=2 fps=0.0\n"
    )
    assert faces.parse_scene_cuts(log) == [12.345, 99.9]
    assert faces.parse_scene_cuts("") == []
    args = faces.scene_cut_args(Path("/v.mp4"), threshold=0.4)
    assert "select='gt(scene,0.4)',showinfo" in args and args[-3:] == ["-f", "null", "-"]
    fa = faces.frames_args(Path("/v.mp4"), Path("/tmp/x"), width=320)
    assert fa[fa.index("-vf") + 1] == "fps=1,scale=320:-2" and fa[-1] == "/tmp/x/f-%06d.jpg"


def test_detector_on_synthetic_frames(tmp_path):
    cv2 = pytest.importorskip("cv2")
    import numpy as np

    blank = tmp_path / "f-000001.jpg"
    cv2.imwrite(str(blank), np.zeros((180, 320), dtype=np.uint8))
    detector = faces.FaceDetector()
    ratios = faces.ratios_for_frames([blank], detector)
    assert ratios == [0.0]
    assert not blank.exists()  # кадр удалён после чтения

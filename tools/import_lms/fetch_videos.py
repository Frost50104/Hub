"""Подготовка видео к импорту: скачивание YouTube + faststart-ремукс.

Hub принимает только собственные mp4 (CSP запрещает встраивание YouTube),
а плеер требует moov-атом в начале файла (`learn_media.mp4_has_faststart`),
иначе видео не начнёт играть до полной загрузки. Поэтому:

* 6 роликов с YouTube качаем через yt-dlp (h264+aac, ≤1080p);
* все mp4 (скачанные и локальные из «Инструкции/») прогоняем ремуксом
  `ffmpeg -c copy -movflags +faststart` — без перекодирования.

Запускается локально при сборке bundle; на VPS не нужен.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
from pathlib import Path

MAX_VIDEO_BYTES = 300 * 1024 * 1024  # media_size_limit(video) в learn_settings


def md5_of(path: Path) -> str:
    digest = hashlib.md5()  # noqa: S324 — дедуп, не крипто
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def has_faststart(path: Path, scan_limit: int = 64) -> bool:
    """moov должен встретиться раньше mdat (копия проверки сервера)."""
    with path.open("rb") as fh:
        for _ in range(scan_limit):
            header = fh.read(8)
            if len(header) < 8:
                return False
            size = int.from_bytes(header[:4], "big")
            box = header[4:8]
            if box == b"moov":
                return True
            if box == b"mdat":
                return False
            if size == 1:  # 64-битный размер
                ext = fh.read(8)
                if len(ext) < 8:
                    return False
                size = int.from_bytes(ext, "big")
                fh.seek(size - 16, 1)
            elif size < 8:
                return False
            else:
                fh.seek(size - 8, 1)
    return False


def remux_faststart(src: Path, dst: Path) -> bool:
    """Ремукс без перекодирования. False — ffmpeg отказался (битый файл)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(  # noqa: S603
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", str(src),
            "-c", "copy", "-movflags", "+faststart",
            str(dst),
        ],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0 or not dst.exists():
        return False
    return has_faststart(dst)


def prepare_local_video(src: Path, out_dir: Path) -> tuple[Path | None, str]:
    """Локальный mp4 → готовый к загрузке файл. Возвращает (путь, причина)."""
    if src.stat().st_size > MAX_VIDEO_BYTES:
        return None, f"больше {MAX_VIDEO_BYTES // 1024 // 1024} МБ"
    out_dir.mkdir(parents=True, exist_ok=True)
    if has_faststart(src):
        dst = out_dir / f"vid_{md5_of(src)[:16]}.mp4"
        if not dst.exists():
            shutil.copy2(src, dst)
        return dst, "готов (faststart уже был)"
    tmp = out_dir / f"tmp_{src.stem[:20]}.mp4"
    if not remux_faststart(src, tmp):
        tmp.unlink(missing_ok=True)
        return None, "ffmpeg не смог сделать faststart"
    dst = out_dir / f"vid_{md5_of(tmp)[:16]}.mp4"
    if dst.exists():
        tmp.unlink(missing_ok=True)
    else:
        tmp.rename(dst)
    return dst, "ремукс faststart"


def fetch_youtube(video_id: str, out_dir: Path) -> tuple[Path | None, str]:
    """Скачать ролик и привести к faststart. Приватный/удалённый → (None, …)."""
    try:
        import yt_dlp
    except ImportError:  # pragma: no cover — инструмент ставится локально
        return None, "yt-dlp не установлен"

    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmpdir:
        template = str(Path(tmpdir) / "%(id)s.%(ext)s")
        opts = {
            "format": (
                "bestvideo[height<=1080][vcodec^=avc1]+bestaudio[acodec^=mp4a]/"
                "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best"
            ),
            "merge_output_format": "mp4",
            "outtmpl": template,
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            # Ролики UPPETIT — unlisted: web-клиент отдаёт «not available»,
            # android/ios отрабатывают штатно.
            "extractor_args": {"youtube": {"player_client": ["android", "ios", "web"]}},
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([f"https://www.youtube.com/watch?v={video_id}"])
        except Exception as exc:  # noqa: BLE001 — любая ошибка ⇒ фолбэк на ссылку
            return None, f"не скачался: {type(exc).__name__}: {exc}"[:200]
        downloaded = sorted(Path(tmpdir).glob(f"{video_id}.*"))
        if not downloaded:
            return None, "файл не появился"
        return prepare_local_video(downloaded[0], out_dir)

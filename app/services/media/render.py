"""Аргументы ffmpeg для чистовика: звук для STT, замер шума и тишины, два
прохода `loudnorm`, рендер одним проходом через `select/aselect`. Чистые
функции: строят команды и скрипт фильтров, бинарь зовёт `ffmpeg.run`."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from app.services.media.edl import Interval, select_expr
from app.services.media.normalize import AAC, FASTSTART, X264

DENOISE_FILTERS = {
    "afftdn": "afftdn=nf=-25:tn=1",
    "none": "",
}


def audio16k_args(src: Path, dst: Path) -> list[str]:
    """Моно 16 кГц PCM — вход для Whisper и для замеров тишины."""
    return ["-i", str(src), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(dst)]


def voice_track_args(src: Path, dst: Path) -> list[str]:
    """Голос для Hedra: моно mp3 96k (лимит 104,8 МБ на файл Hedra держит с запасом)."""
    codec = ["-c:a", "libmp3lame", "-b:a", "96k"]
    return ["-i", str(src), "-vn", "-ac", "1", "-ar", "44100", *codec, str(dst)]


def noise_floor_args(wav: Path) -> list[str]:
    return [
        "-i",
        str(wav),
        "-af",
        "astats=measure_overall=Noise_floor:measure_perchannel=none",
        "-f",
        "null",
        "-",
    ]


def silencedetect_args(wav: Path, *, threshold_db: float, min_pause: float) -> list[str]:
    return [
        "-i",
        str(wav),
        "-af",
        f"silencedetect=n={threshold_db:g}dB:d={min_pause:g}",
        "-f",
        "null",
        "-",
    ]


def denoise_filter(kind: str, *, rnnoise_model: Path | None = None) -> str:
    if kind == "arnndn":
        if rnnoise_model is None:
            raise ValueError("arnndn требует файл модели rnnoise")
        return f"arnndn=m={rnnoise_model}"
    if kind not in DENOISE_FILTERS:
        raise ValueError(f"Неизвестный шумодав: {kind!r}")
    return DENOISE_FILTERS[kind]


def _audio_chain(kept: Iterable[Interval], denoise: str) -> list[str]:
    chain = [f"aselect='{select_expr(kept)}'", "asetpts=N/SR/TB"]
    if denoise:
        chain.append(denoise)
    return chain


def loudnorm_target(*, i: float, tp: float, lra: float) -> str:
    return f"loudnorm=I={i:g}:TP={tp:g}:LRA={lra:g}"


def loudnorm_pass1_args(
    src: Path,
    kept: Iterable[Interval],
    *,
    denoise: str,
    i: float,
    tp: float,
    lra: float,
) -> list[str]:
    """Первый проход только по звуку: измерить громкость УЖЕ вырезанного и
    очищенного трека (иначе ужатые паузы и шум сдвинули бы замер)."""
    loud = loudnorm_target(i=i, tp=tp, lra=lra) + ":print_format=json"
    chain = [*_audio_chain(kept, denoise), loud]
    return ["-i", str(src), "-vn", "-af", ",".join(chain), "-f", "null", "-"]


def filter_script(
    kept: Iterable[Interval],
    *,
    denoise: str,
    i: float,
    tp: float,
    lra: float,
    measured: dict[str, float],
    fps: float,
    scale_cap: int,
) -> str:
    """Текст для `-filter_complex_script`: одна видео- и одна аудио-ветка."""
    kept = list(kept)
    video = (
        f"[0:v]select='{select_expr(kept)}',setpts=N/FRAME_RATE/TB,"
        f"fps={fps:g},scale=-2:'min(ih,{scale_cap})':flags=bicubic,format=yuv420p[v]"
    )
    loud = (
        loudnorm_target(i=i, tp=tp, lra=lra)
        + f":measured_I={measured['input_i']:g}:measured_TP={measured['input_tp']:g}"
        + f":measured_LRA={measured['input_lra']:g}:measured_thresh={measured['input_thresh']:g}"
        + f":offset={measured.get('target_offset', 0.0):g}:linear=true:print_format=summary"
    )
    audio = "[0:a]" + ",".join([*_audio_chain(kept, denoise), loud]) + "[a]"
    return video + ";\n" + audio + "\n"


def render_args(src: Path, dst: Path, script: Path, *, threads: int = 1) -> list[str]:
    return [
        "-i",
        str(src),
        "-filter_complex_script",
        str(script),
        "-map",
        "[v]",
        "-map",
        "[a]",
        *X264,
        "-threads",
        str(threads),
        *AAC,
        *FASTSTART,
        str(dst),
    ]

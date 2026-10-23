"""План чистовика — чистая математика над параметрами, уровнями звука и
транскриптом: какие куски вырезать, что останется, какая статистика уйдёт в
`result` и в шторку «до/после». Без ffmpeg и БД — под юнит-тестами.

Две вырезки разной природы: ПАУЗЫ ужимаются (середина уходит, края остаются —
решение владельца 22.10), ПЕРЕЗАПИСИ (`cuts`: брак дублей по `retakes.py` или
явный выбор автора) вырезаются целиком.

Паузы ищутся по зазорам между СЛОВАМИ транскрипта и уровню звука в них
(`levels.pauses_from_gaps`); пути без уровней (`silences`) и без транскрипта
(тихие отрезки по кадрам) остаются для старых заданий и STT-less стендов.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.media import edl, levels
from app.services.media.edl import Interval
from app.services.media.levels import Frame


@dataclass(frozen=True)
class CleanupParams:
    min_pause_sec: float = 1.5
    keep_sec: float = 0.7
    margin_sec: float = 0.2
    denoise: str = "afftdn"
    loudnorm: bool = True
    loudnorm_i: float = -16.0
    loudnorm_tp: float = -1.5
    loudnorm_lra: float = 11.0
    fps_cap: float = 30.0
    scale_cap: int = 1080
    # Порог «громко» — на столько дБ тише медианы речи (`levels.threshold_db`).
    speech_offset_db: float = 15.0
    # Зазор между словами считается паузой, если громкого времени в нём не больше.
    max_loud_fraction: float = 0.5
    # Уверенные перезаписи режутся сами (решение владельца 23.10); автор может
    # прислать явный список `cuts` вместо автоматики.
    retakes: bool = True

    @classmethod
    def from_settings(cls, defaults: dict[str, Any], overrides: dict[str, Any]) -> CleanupParams:
        """Дефолты тенанта (`media_cleanup_defaults`) + переопределения заказа.
        `min_pause_sec = 0` / `None` — паузы не трогать (вариант «Не трогать паузы»)."""
        merged = {
            **(defaults or {}),
            **{k: v for k, v in (overrides or {}).items() if v is not None},
        }
        raw_pause = merged.get("min_pause_sec", 1.5)
        return cls(
            min_pause_sec=float(raw_pause) if raw_pause else 0.0,
            keep_sec=float(merged.get("keep_sec", 0.7)),
            margin_sec=float(merged.get("margin_sec", 0.2)),
            denoise=str(merged.get("denoise", "afftdn")),
            loudnorm=bool(merged.get("loudnorm", True)),
            loudnorm_i=float(merged.get("loudnorm_i", -16)),
            loudnorm_tp=float(merged.get("loudnorm_tp", -1.5)),
            loudnorm_lra=float(merged.get("loudnorm_lra", 11)),
            fps_cap=float(merged.get("fps_cap", 30)),
            scale_cap=int(merged.get("scale_cap", 1080)),
            speech_offset_db=float(merged.get("speech_offset_db", 15.0)),
            max_loud_fraction=float(merged.get("max_loud_fraction", 0.5)),
            retakes=bool(merged.get("retakes", True)),
        )

    @property
    def pauses_enabled(self) -> bool:
        return self.min_pause_sec > 0

    def to_json(self) -> dict[str, Any]:
        return {
            "min_pause_sec": self.min_pause_sec,
            "keep_sec": self.keep_sec,
            "margin_sec": self.margin_sec,
            "denoise": self.denoise,
            "loudnorm": self.loudnorm,
            "loudnorm_i": self.loudnorm_i,
            "loudnorm_tp": self.loudnorm_tp,
            "loudnorm_lra": self.loudnorm_lra,
            "fps_cap": self.fps_cap,
            "scale_cap": self.scale_cap,
            "speech_offset_db": self.speech_offset_db,
            "max_loud_fraction": self.max_loud_fraction,
            "retakes": self.retakes,
        }


@dataclass
class CleanupPlan:
    params: CleanupParams
    duration: float
    pauses: list[Interval]
    removed: list[Interval]
    kept: list[Interval]
    cuts: list[Interval] = field(default_factory=list)
    report: list[dict[str, Any]] = field(default_factory=list)

    @property
    def removed_sec(self) -> float:
        return edl.total(self.removed)

    @property
    def cuts_sec(self) -> float:
        return edl.total(self.cuts)

    @property
    def output_sec(self) -> float:
        return max(0.0, self.duration - self.removed_sec)

    def stats(self) -> dict[str, Any]:
        return {
            "source_sec": round(self.duration, 2),
            "output_sec": round(self.output_sec, 2),
            "removed_sec": round(self.removed_sec, 2),
            "pauses": len(self.pauses),
            "retakes": len(self.cuts),
            "retakes_sec": round(self.cuts_sec, 2),
        }


def _context_for(
    pause: Interval, segments: list[dict[str, Any]] | None, *, max_words: int = 5
) -> str | None:
    """Подпись паузы — хвост реплики перед ней («после „нажимаем Сохранить“»).
    Реплика ищется по словам: пауза может стоять внутри реплики Whisper."""
    if not segments:
        return None
    start = pause[0]
    tail: list[str] = []
    for seg in segments:
        words = seg.get("w") or []
        if words:
            for w in words:
                if float(w[1]) <= start + 0.3:
                    tail.append(str(w[2]))
                    tail = tail[-max_words:]
        elif float(seg["e"]) <= start + 0.3:
            text = str(seg.get("t") or "").strip()
            if text:
                tail = text.split()[-max_words:]
    joined = " ".join(tail).strip().rstrip(".!?…,")
    return f"после «{joined}»" if joined else None


def plan_cleanup(
    params: CleanupParams,
    *,
    duration: float,
    segments: list[dict[str, Any]] | None,
    silences: list[Interval] | None = None,
    frames: list[Frame] | None = None,
    threshold_db: float | None = None,
    cuts: list[Interval] | None = None,
    report_limit: int = 200,
) -> CleanupPlan:
    """Паузы: с `frames` — зазоры между словами с долей громкого ≤ порога
    (`levels.pauses_from_gaps`); без транскрипта — тихие отрезки по кадрам;
    без `frames` (старый путь) — тишина ∩ зазоры. Из каждой паузы удаляется
    середина, края остаются (`edl`). `cuts` вырезаются целиком."""
    cut_list = edl.normalize(
        [(max(0.0, s), min(float(duration), e)) for s, e in (cuts or []) if e > s]
    )
    cut_list = [(s, e) for s, e in cut_list if e - s > edl.EPS]
    if not params.pauses_enabled:
        pauses: list[Interval] = []
    elif frames is not None:
        thr = threshold_db if threshold_db is not None else levels.DEFAULT_THRESHOLD_DB
        if segments:
            from app.services.media.transcription.base import transcript_gaps

            gaps = transcript_gaps(segments, duration)
            pauses = levels.pauses_from_gaps(
                gaps,
                frames,
                thr,
                min_pause=params.min_pause_sec,
                max_loud_fraction=params.max_loud_fraction,
            )
        else:
            pauses = levels.silent_runs(frames, thr, min_len=params.min_pause_sec)
    else:
        gaps = None
        if segments:
            from app.services.media.transcription.base import transcript_gaps

            gaps = transcript_gaps(segments, duration)
        pauses = edl.pauses(silences or [], gaps, min_pause=params.min_pause_sec)
    # Вырезка перезаписи забирает своё: остаток паузы считается заново и
    # короче порога паузой не является.
    pauses = [
        p for p in edl.subtract(pauses, cut_list) if p[1] - p[0] >= params.min_pause_sec - edl.EPS
    ]
    compressed = edl.compress_pauses(pauses, keep=params.keep_sec, margin=params.margin_sec)
    removed = edl.normalize([*compressed, *cut_list])
    kept = edl.kept_intervals(removed, duration)
    report: list[dict[str, Any]] = []
    for pause in pauses[:report_limit]:
        cut_sec = edl.total(edl.intersect([pause], removed))
        report.append(
            {
                "at": round(edl.remap_time(pause[0], removed), 2),
                "source_at": round(pause[0], 2),
                "was_sec": round(pause[1] - pause[0], 2),
                "now_sec": round(pause[1] - pause[0] - cut_sec, 2),
                "context": _context_for(pause, segments),
            }
        )
    return CleanupPlan(params, duration, pauses, removed, kept, cut_list, report)

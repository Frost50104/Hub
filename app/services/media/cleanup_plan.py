"""План чистовика — чистая математика над параметрами, тишиной и транскриптом:
какие куски вырезать, что останется, какая статистика уйдёт в `result` и в
шторку «до/после». Без ffmpeg и БД — под юнит-тестами."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.media import edl
from app.services.media.edl import Interval


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
        }


@dataclass
class CleanupPlan:
    params: CleanupParams
    duration: float
    pauses: list[Interval]
    removed: list[Interval]
    kept: list[Interval]
    report: list[dict[str, Any]] = field(default_factory=list)

    @property
    def removed_sec(self) -> float:
        return edl.total(self.removed)

    @property
    def output_sec(self) -> float:
        return max(0.0, self.duration - self.removed_sec)

    def stats(self) -> dict[str, Any]:
        return {
            "source_sec": round(self.duration, 2),
            "output_sec": round(self.output_sec, 2),
            "removed_sec": round(self.removed_sec, 2),
            "pauses": len(self.pauses),
        }


def _context_for(
    pause: Interval, segments: list[dict[str, Any]] | None, *, max_words: int = 5
) -> str | None:
    """Подпись паузы — хвост реплики перед ней («после „нажимаем Сохранить“»)."""
    if not segments:
        return None
    start = pause[0]
    before = [s for s in segments if float(s["e"]) <= start + 0.3]
    if not before:
        return None
    text = str(before[-1].get("t") or "").strip()
    if not text:
        return None
    words = text.rstrip(".!?…").split()
    tail = " ".join(words[-max_words:])
    return f"после «{tail}»" if tail else None


def plan_cleanup(
    params: CleanupParams,
    *,
    duration: float,
    silences: list[Interval],
    segments: list[dict[str, Any]] | None,
    report_limit: int = 200,
) -> CleanupPlan:
    """Паузы = тишина ∩ зазоры транскрипта (без транскрипта — только тишина),
    длиннее порога; из каждой удаляется середина, края остаются (`edl`)."""
    if not params.pauses_enabled:
        return CleanupPlan(params, duration, [], [], [(0.0, float(duration))])
    gaps = None
    if segments:
        from app.services.media.transcription.base import transcript_gaps

        gaps = transcript_gaps(segments, duration)
    pauses = edl.pauses(silences, gaps, min_pause=params.min_pause_sec)
    removed = edl.compress_pauses(pauses, keep=params.keep_sec, margin=params.margin_sec)
    kept = edl.kept_intervals(removed, duration)
    report: list[dict[str, Any]] = []
    for pause in pauses[:report_limit]:
        cut = [r for r in removed if r[0] >= pause[0] - 1e-6 and r[1] <= pause[1] + 1e-6]
        cut_sec = edl.total(cut)
        report.append(
            {
                "at": round(edl.remap_time(pause[0], removed), 2),
                "source_at": round(pause[0], 2),
                "was_sec": round(pause[1] - pause[0], 2),
                "now_sec": round(pause[1] - pause[0] - cut_sec, 2),
                "context": _context_for(pause, segments),
            }
        )
    return CleanupPlan(params, duration, pauses, removed, kept, report)

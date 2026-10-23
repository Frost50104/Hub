"""План чистовика: параметры из дефолтов тенанта и заказа, паузы по тишине и
транскрипту, отчёт для шторки «до/после»."""

from __future__ import annotations

import pytest

from app.services.media.cleanup_plan import CleanupParams, plan_cleanup

DEFAULTS = {
    "min_pause_sec": 1.5,
    "keep_sec": 0.7,
    "margin_sec": 0.2,
    "denoise": "afftdn",
    "loudnorm_i": -16,
    "loudnorm_tp": -1.5,
    "loudnorm_lra": 11,
    "fps_cap": 30,
    "scale_cap": 1080,
}


def test_params_merge_overrides_and_zero_pause_disables():
    p = CleanupParams.from_settings(
        DEFAULTS, {"min_pause_sec": 2.0, "loudnorm": False, "denoise": None}
    )
    assert p.min_pause_sec == 2.0 and p.loudnorm is False and p.denoise == "afftdn"
    assert p.pauses_enabled
    off = CleanupParams.from_settings(DEFAULTS, {"min_pause_sec": 0})
    assert not off.pauses_enabled
    assert CleanupParams.from_settings({}, {}).to_json()["keep_sec"] == 0.7


def test_plan_uses_transcript_gaps_and_reports_context():
    params = CleanupParams.from_settings(DEFAULTS, {})
    segments = [
        {"s": 0.0, "e": 10.0, "t": "Добрый день, коллеги."},
        {"s": 14.0, "e": 20.0, "t": "Нажимаем Сохранить."},
        {"s": 21.0, "e": 30.0, "t": "Готово"},
    ]
    silences = [
        (9.5, 14.2),
        (20.2, 20.9),
        (25.0, 27.5),
    ]  # вторая короче порога, третья — внутри речи
    plan = plan_cleanup(params, duration=30.0, silences=silences, segments=segments)
    assert plan.pauses == [(10.0, 14.0)]
    assert plan.removed == [(10.35, 13.65)]
    assert plan.removed_sec == pytest.approx(3.3)
    assert plan.output_sec == pytest.approx(26.7)
    assert plan.stats() == {
        "source_sec": 30.0,
        "output_sec": 26.7,
        "removed_sec": 3.3,
        "pauses": 1,
        "retakes": 0,
        "retakes_sec": 0.0,
    }
    report = plan.report[0]
    assert report["source_at"] == 10.0 and report["at"] == 10.0
    assert report["was_sec"] == 4.0 and report["now_sec"] == pytest.approx(0.7)
    assert report["context"] == "после «Добрый день, коллеги»"


def _frames(pattern: str, *, step: float = 0.1):
    return [(round(i * step, 3), -30.0 if ch == "L" else -70.0) for i, ch in enumerate(pattern)]


def test_plan_by_levels_finds_pauses_inside_whisper_segment():
    """Реплика Whisper 0–4 с, а между словами дыра 1,0–3,0 — по репликам зазора
    нет, по словам есть; щелчок на 2,0 паузе не мешает."""
    params = CleanupParams.from_settings(DEFAULTS, {})
    segments = [
        {
            "s": 0.0,
            "e": 4.0,
            "t": "Hub. Что же",
            "w": [[0.0, 1.0, "Hub."], [3.0, 3.5, "Что"], [3.5, 4.0, "же"]],
        }
    ]
    frames = _frames("LLLLLLLLLL..........L.........LLLLLLLLLL")
    plan = plan_cleanup(params, duration=4.0, segments=segments, frames=frames, threshold_db=-45.0)
    assert plan.pauses == [(1.0, 3.0)]
    assert plan.removed == [(1.35, 2.65)]
    assert plan.report[0]["context"] == "после «Hub»"
    # Тот же зазор с речью, которую Whisper пропустил, — не пауза.
    loud = _frames("LLLLLLLLLLLLLLLLLLLLLLLLLLLLLLLLLLLLLLLL")
    plan2 = plan_cleanup(params, duration=4.0, segments=segments, frames=loud, threshold_db=-45.0)
    assert plan2.pauses == []


def test_plan_without_transcript_uses_silent_runs_from_levels():
    params = CleanupParams.from_settings(DEFAULTS, {"min_pause_sec": 1.0})
    frames = _frames("LLLLL" + "." * 20 + "LLLLL")
    plan = plan_cleanup(params, duration=3.0, segments=None, frames=frames, threshold_db=-45.0)
    assert plan.pauses == [(0.5, 2.5)]


def test_plan_cuts_remove_whole_spans_and_swallow_inner_pauses():
    params = CleanupParams.from_settings(DEFAULTS, {})
    segments = [
        {
            "s": 0.0,
            "e": 2.0,
            "t": "Выбираем проект.",
            "w": [[0.0, 1.0, "Выбираем"], [1.0, 2.0, "проект."]],
        },
        {
            "s": 6.0,
            "e": 8.0,
            "t": "Выбираем проект.",
            "w": [[6.0, 7.0, "Выбираем"], [7.0, 8.0, "проект."]],
        },
    ]
    frames = _frames("L" * 20 + "." * 40 + "L" * 20 + "." * 20)
    plan = plan_cleanup(
        params,
        duration=10.0,
        segments=segments,
        frames=frames,
        threshold_db=-45.0,
        cuts=[(0.0, 5.9)],
    )
    # Пауза 2–6 целиком внутри вырезки — не считается; хвост 8–10 остаётся паузой.
    assert plan.cuts == [(0.0, 5.9)]
    assert plan.pauses == [(8.0, 10.0)]
    assert plan.removed[0] == (0.0, 5.9)
    assert plan.stats()["retakes"] == 1 and plan.stats()["retakes_sec"] == 5.9
    assert plan.output_sec == pytest.approx(10.0 - 5.9 - 1.3)
    # Вырезки режутся по длительности и нормализуются; пустые — выбрасываются.
    plan2 = plan_cleanup(
        params, duration=10.0, segments=None, frames=frames, cuts=[(9.0, 20.0), (3.0, 2.0)]
    )
    assert plan2.cuts == [(9.0, 10.0)]
    assert CleanupParams.from_settings(DEFAULTS, {"retakes": False}).retakes is False
    assert CleanupParams.from_settings(DEFAULTS, {}).to_json()["max_loud_fraction"] == 0.5


def test_plan_without_transcript_uses_silence_only_and_remaps_later_pauses():
    params = CleanupParams.from_settings(DEFAULTS, {})
    plan = plan_cleanup(params, duration=60.0, silences=[(5.0, 8.0), (30.0, 33.0)], segments=None)
    assert plan.pauses == [(5.0, 8.0), (30.0, 33.0)]
    # Вторая пауза в чистовике стоит раньше на длину первой вырезки.
    assert plan.report[1]["at"] == pytest.approx(30.0 - 2.3)
    assert plan.report[1]["context"] is None
    assert plan.kept[0] == (0.0, 5.35)


def test_plan_pauses_disabled_keeps_everything():
    params = CleanupParams.from_settings(DEFAULTS, {"min_pause_sec": 0})
    plan = plan_cleanup(params, duration=42.0, silences=[(1, 5)], segments=None)
    assert plan.pauses == [] and plan.removed == [] and plan.kept == [(0.0, 42.0)]
    assert plan.output_sec == 42.0

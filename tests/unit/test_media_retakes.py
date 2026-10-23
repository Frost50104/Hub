"""Перезаписи по транскрипту: голосовые метки, повтор начала фразы, уверенность,
границы вырезки, слияние пересечений."""

from __future__ import annotations

import pytest

from app.services.media import retakes


def seg(words: list[tuple[float, float, str]], *, text: str | None = None) -> dict:
    return {
        "s": words[0][0],
        "e": words[-1][1],
        "t": text if text is not None else " ".join(w[2] for w in words),
        "w": [[s, e, t] for s, e, t in words],
    }


def phrase(start: float, text: str, *, step: float = 0.4) -> list[tuple[float, float, str]]:
    out = []
    t = start
    for word in text.split():
        out.append((round(t, 3), round(t + step * 0.8, 3), word))
        t += step
    return out


def test_marker_utterance_rules():
    assert retakes.is_marker_utterance(["стоп"])
    assert retakes.is_marker_utterance(["так", "стоп", "зановал"])
    assert retakes.is_marker_utterance(["еще", "раз", "пишу"])
    assert retakes.is_marker_utterance(["это", "вырезаем"])
    # Содержательные слова рядом с меткой — не метка.
    assert not retakes.is_marker_utterance(["стоп", "на", "платформе", "проехали"])
    assert not retakes.is_marker_utterance(["проваливаемся", "еще", "раз", "в", "ассистент"])
    # «Раз» и «ещё» порознь — обычные слова.
    assert not retakes.is_marker_utterance(["раз"])
    assert not retakes.is_marker_utterance([])


def test_marker_cuts_aborted_take_up_to_restart():
    # «Важно, весь офис… Стоп. Важно, весь офис компании переходит…»
    bad = phrase(10.0, "Важно, весь офис")
    marker = [(12.0, 12.4, "Стоп.")]
    good = phrase(15.0, "Важно, весь офис компании переходит")
    items = retakes.find_retakes([seg(bad), seg(marker), seg(good)], duration=30.0)
    assert len(items) == 1
    r = items[0]
    assert r.reason == "marker" and r.confidence == "high" and r.marker == "Стоп."
    # Начало — чуть раньше «Важно,», конец — чуть раньше перезапуска.
    assert r.start == pytest.approx(10.0 - retakes.LEAD_SEC)
    assert r.end == pytest.approx(15.0 - retakes.LEAD_SEC)
    assert r.before.startswith("Важно, весь офис") and r.after.startswith("Важно, весь офис")


def test_marker_without_repeat_cuts_only_marker_with_short_tail():
    speech = phrase(0.0, "Нажимаем на кнопку Сохранить.")
    marker = [(5.0, 5.3, "Заново.")]
    good = phrase(20.0, "Переходим к следующему разделу.")
    items = retakes.find_retakes([seg(speech), seg(marker), seg(good)], duration=40.0)
    assert len(items) == 1
    r = items[0]
    assert r.confidence == "high" and r.before == "Заново."
    assert r.start == pytest.approx(5.0 - retakes.LEAD_SEC)
    # Хвост тишины после метки — не длиннее MARKER_TAIL_SEC (остальное ужмёт правило пауз).
    assert r.end == pytest.approx(5.3 + retakes.MARKER_TAIL_SEC)


def test_two_markers_in_a_row_are_one_run():
    bad = phrase(0.0, "Выбираем проект.")
    m1 = [(2.0, 2.3, "Так,"), (2.3, 2.6, "стоп.")]
    m2 = [(3.0, 3.5, "Зановал.")]
    good = phrase(6.0, "Выбираем проект. У нас появляется")
    items = retakes.find_retakes([seg(bad), seg(m1), seg(m2), seg(good)], duration=20.0)
    assert len(items) == 1
    assert items[0].marker == "Так, стоп. Зановал."
    assert items[0].start == pytest.approx(0.0)
    assert items[0].end == pytest.approx(6.0 - retakes.LEAD_SEC)


def test_repeat_after_gap_confidence_levels():
    # Три слова совпали — уверенно.
    bad = phrase(0.0, "Задача у нас составлена, задачу можно")
    good = phrase(6.0, "Задача у нас готова, можем задачу закрыть")
    items = retakes.find_retakes([seg(bad), seg(good)], duration=20.0)
    assert [(r.reason, r.confidence) for r in items] == [("repeat", "high")]
    assert items[0].end == pytest.approx(6.0 - retakes.LEAD_SEC)
    # Одно слово ≥ 4 букв и короткий брак — неуверенно.
    bad1 = phrase(0.0, "Выбираем учётную запись,")
    good1 = phrase(5.0, "выбираем профиль и связь")
    items1 = retakes.find_retakes([seg(bad1), seg(good1)], duration=20.0)
    assert [(r.reason, r.confidence) for r in items1] == [("repeat", "low")]
    # Два частых слова и разные фразы дальше — неуверенно.
    bad2 = phrase(0.0, "мы можем через собаку добавить пользователя")
    good2 = phrase(6.0, "мы можем посмотреть историю задач и комментарии")
    items2 = retakes.find_retakes([seg(bad2), seg(good2)], duration=20.0)
    assert [(r.reason, r.confidence) for r in items2] == [("repeat", "low")]
    # Без паузы между фразами повтор не ищется.
    items3 = retakes.find_retakes([seg(bad + phrase(2.8, "Задача у нас готова"))], duration=20.0)
    assert items3 == []


def test_repeat_chain_starts_at_earliest_take():
    t1 = phrase(0.0, "Мы попали на страницу.")
    t2 = phrase(5.0, "Мы попали на платформу.")
    t3 = phrase(12.0, "Мы попали на платформу Dashboard. На левой панели")
    items = retakes.find_retakes([seg(t1), seg(t2), seg(t3)], duration=30.0)
    assert len(items) == 1
    assert items[0].confidence == "high"
    assert items[0].start == pytest.approx(0.0)
    assert items[0].end == pytest.approx(12.0 - retakes.LEAD_SEC)


def test_mixed_marker_utterance_is_low_and_overlaps_resolve():
    chatter = phrase(0.0, "Так, проехали, стоп, понеслась звезда по кочкам.")
    good = phrase(6.0, "Погнали дальше на самое начало.")
    items = retakes.find_retakes([seg(chatter), seg(good)], duration=20.0)
    assert [(r.reason, r.confidence) for r in items] == [("marker", "low")]
    assert items[0].marker.startswith("Так, проехали")
    # Пересечение: уверенный поглощает неуверенного.
    merged = retakes._dedupe(
        [
            retakes.Retake(1.0, 5.0, "repeat", "low", None, "a", "b"),
            retakes.Retake(2.0, 6.0, "marker", "high", "Стоп.", "c", "d"),
        ]
    )
    assert [(r.start, r.end, r.confidence) for r in merged] == [(2.0, 6.0, "high")]
    merged2 = retakes._dedupe(
        [
            retakes.Retake(1.0, 5.0, "marker", "high", "Стоп.", "a", "b"),
            retakes.Retake(4.0, 8.0, "repeat", "high", None, "c", "d"),
        ]
    )
    assert [(r.start, r.end, r.reason) for r in merged2] == [(1.0, 8.0, "marker")]


def test_segments_without_words_and_json_shape():
    segs = [
        {"s": 0.0, "e": 2.0, "t": "Выбираем проект."},
        {"s": 5.0, "e": 8.0, "t": "Выбираем проект. У нас появляется список."},
    ]
    items = retakes.find_retakes(segs, duration=10.0)
    assert len(items) == 1 and items[0].confidence == "high"
    data = items[0].to_json()
    assert set(data) == {"s", "e", "reason", "confidence", "marker", "before", "after"}
    assert retakes.high_confidence_cuts(items) == [(items[0].start, items[0].end)]
    assert retakes.find_retakes([], duration=10.0) == []

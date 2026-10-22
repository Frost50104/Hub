"""Сторож галлюцинаций, сшивка кусков, зазоры и сериализация транскрипта."""

from __future__ import annotations

from app.services.media.transcription import base
from app.services.media.transcription.base import Segment, Word


def seg(s, e, t, **kw):
    return Segment(start=s, end=e, text=t, **kw)


def test_hallucination_guard():
    assert base.hallucination_guard(seg(0, 1, "Привет"))
    assert not base.hallucination_guard(seg(0, 1, "   "))
    assert not base.hallucination_guard(seg(0, 1, "..."))
    assert not base.hallucination_guard(seg(0, 1, "Субтитры сделал DimaTorzok"))
    assert not base.hallucination_guard(seg(0, 1, "Продолжение следует..."))
    assert not base.hallucination_guard(seg(0, 1, "да да да да", compression_ratio=3.0))
    assert not base.hallucination_guard(seg(0, 1, "шум", no_speech_prob=0.9, avg_logprob=-1.5))
    # Одного признака мало (как в Listen: оба порога разом).
    assert base.hallucination_guard(seg(0, 1, "тихо", no_speech_prob=0.9, avg_logprob=-0.5))
    assert base.hallucination_guard(seg(0, 1, "тихо", no_speech_prob=0.3, avg_logprob=-1.5))


def test_stitch_joins_across_chunk_boundary_without_sentence_end():
    chunks = [
        (0.0, [seg(0, 2, "Сегодня мы")]),
        (2.0, [seg(0.1, 1.5, "поговорим о Hub."), seg(2.0, 3.0, "Начнём.")]),
    ]
    out = base.stitch(chunks)
    assert [s.text for s in out] == ["Сегодня мы поговорим о Hub.", "Начнём."]
    assert (out[0].start, out[0].end) == (0.0, 3.5)
    assert (out[1].start, out[1].end) == (4.0, 5.0)


def test_stitch_respects_sentence_end_and_gap():
    chunks = [(0.0, [seg(0, 2, "Готово.")]), (2.0, [seg(0.1, 1, "Дальше")])]
    assert [s.text for s in base.stitch(chunks)] == ["Готово.", "Дальше"]
    chunks = [(0.0, [seg(0, 2, "Без точки")]), (2.0, [seg(0.5, 1, "далеко")])]
    assert [s.text for s in base.stitch(chunks)] == ["Без точки", "далеко"]
    assert base.stitch([]) == []


def test_offset_words_json_and_plain_text():
    s = seg(0, 1, "a", words=[Word(0.0, 0.5, "a")])
    out = base.offset_segments([s], 10)
    assert out[0].words[0].start == 10.0
    assert base.segments_to_json(out) == [
        {"s": 10.0, "e": 11.0, "t": "a", "w": [[10.0, 10.5, "a"]]}
    ]
    assert base.segments_to_json([seg(0, 1, " b ")]) == [{"s": 0.0, "e": 1.0, "t": "b"}]
    assert base.plain_text([seg(0, 1, " a "), seg(1, 2, ""), seg(2, 3, "b")]) == "a b"


def test_transcript_gaps():
    gaps = base.transcript_gaps([{"s": 1, "e": 2}, {"s": 2.5, "e": 4}], 5)
    assert gaps == [(0.0, 1.0), (2.0, 2.5), (4.0, 5.0)]
    assert base.transcript_gaps([], 3) == [(0.0, 3.0)]
    assert base.transcript_gaps([seg(0, 3, "x")], 3) == []

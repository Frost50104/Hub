"""WebVTT из сегментов: правила cue, переносы, непересечение."""

from __future__ import annotations

from app.services.media import vtt


def _ts(s: str) -> float:
    h, m, rest = s.split(":")
    return int(h) * 3600 + int(m) * 60 + float(rest)


def _parse(text: str) -> list[tuple[float, float, str]]:
    blocks = text.strip().split("\n\n")
    assert blocks[0] == "WEBVTT"
    out = []
    for block in blocks[1:]:
        lines = block.split("\n")
        start, _, end = lines[0].partition(" --> ")
        out.append((_ts(start), _ts(end), "\n".join(lines[1:])))
    return out


def test_fmt_ts():
    assert vtt.fmt_ts(0) == "00:00:00.000"
    assert vtt.fmt_ts(3661.5) == "01:01:01.500"
    assert vtt.fmt_ts(-1) == "00:00:00.000"
    assert vtt.fmt_ts(59.9996) == "00:01:00.000"


def test_wrap_lines_two_lines_max_no_words_lost():
    text = " ".join(["слово"] * 20)
    lines = vtt.wrap_lines(text).split("\n")
    assert len(lines) == 2
    assert len(lines[0]) <= 42
    assert " ".join(lines) == text
    assert vtt.wrap_lines("коротко") == "коротко"


def test_build_vtt_basic_and_order():
    segs = [{"s": 2.0, "e": 4.0, "t": "второй"}, {"s": 0.0, "e": 1.5, "t": "первый"}]
    out = vtt.build_vtt(segs)
    assert out.startswith("WEBVTT\n\n")
    assert out.index("первый") < out.index("второй")
    assert "00:00:00.000 --> 00:00:01.500\nпервый" in out
    assert _parse(out) == [(0.0, 1.5, "первый"), (2.0, 4.0, "второй")]


def test_build_vtt_splits_long_segment_by_words():
    words = [[i * 0.5, i * 0.5 + 0.4, f"w{i}"] for i in range(40)]
    segs = [{"s": 0.0, "e": 20.0, "t": " ".join(w[2] for w in words), "w": words}]
    cues = _parse(vtt.build_vtt(segs))
    assert len(cues) >= 3
    for s, e, text in cues:
        assert e - s <= 7.0 + 1e-6
        assert all(len(line) <= 42 for line in text.split("\n"))
    assert " ".join(t.replace("\n", " ") for _, _, t in cues) == segs[0]["t"]


def test_build_vtt_splits_long_segment_without_words():
    text = " ".join(["слово"] * 40)  # 239 знаков, 10 с
    cues = _parse(vtt.build_vtt([{"s": 0.0, "e": 10.0, "t": text}]))
    assert len(cues) >= 3
    assert " ".join(t.replace("\n", " ") for _, _, t in cues) == text
    assert cues[0][0] == 0.0 and cues[-1][1] == 10.0


def test_build_vtt_no_overlap_and_min_length():
    segs = [{"s": 0.0, "e": 0.3, "t": "короткий"}, {"s": 0.5, "e": 3.0, "t": "длинный"}]
    cues = _parse(vtt.build_vtt(segs))
    assert cues == [(0.0, 0.5, "короткий"), (0.5, 3.0, "длинный")]
    # Одиночный короткий — дотягивается до секунды.
    assert _parse(vtt.build_vtt([{"s": 0.0, "e": 0.3, "t": "один"}])) == [(0.0, 1.0, "один")]


def test_build_vtt_overlapping_input_pushed():
    segs = [{"s": 0.0, "e": 3.0, "t": "a"}, {"s": 2.0, "e": 5.0, "t": "b"}]
    assert _parse(vtt.build_vtt(segs)) == [(0.0, 3.0, "a"), (3.0, 5.0, "b")]


def test_build_vtt_empty_and_blank():
    assert vtt.build_vtt([]) == "WEBVTT\n"
    assert vtt.build_vtt([{"s": 0, "e": 1, "t": "  "}]) == "WEBVTT\n"

"""Юнит-тесты lesson_content: валидация extra-нод, гейты, consumer-подготовка."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from app.services.lesson_content import (
    check_answer,
    collect_gate_blocks,
    collect_media_ids,
    collect_required_videos,
    prepare_for_consumer,
    validate_lesson_content,
)
from app.services.rich_content import RichContentError


def _doc(*nodes: dict) -> dict:
    return {"schema": 1, "doc": {"type": "doc", "content": list(nodes)}}


def _p(text: str = "hi") -> dict:
    return {"type": "paragraph", "content": [{"type": "text", "text": text}]}


def _video(media_id: str, *, require: bool = False) -> dict:
    return {
        "type": "video",
        "attrs": {"mediaId": media_id, "requireFullWatch": require},
    }


def _check_q(block_id: str, *, correct: int = 1, gate: bool = False) -> dict:
    return {
        "type": "checkQuestion",
        "attrs": {
            "blockId": block_id,
            "question": "Сколько будет 2+2?",
            "options": ["3", "4", "5"],
            "correct": correct,
            "gateNext": gate,
        },
    }


MEDIA = str(uuid4())


class TestValidate:
    def test_valid_lesson(self):
        payload = _doc(_p(), _video(MEDIA, require=True), _check_q("b1", gate=True))
        assert validate_lesson_content(payload) is payload

    def test_figure_bad_media_id(self):
        with pytest.raises(RichContentError, match="mediaId"):
            validate_lesson_content(
                _doc({"type": "figure", "attrs": {"mediaId": "../etc/passwd"}})
            )

    def test_gallery_empty(self):
        with pytest.raises(RichContentError, match="gallery"):
            validate_lesson_content(_doc({"type": "gallery", "attrs": {"items": []}}))

    def test_check_question_correct_out_of_range(self):
        with pytest.raises(RichContentError, match="correct"):
            validate_lesson_content(_doc(_check_q("b1", correct=7)))

    def test_check_question_needs_block_id(self):
        bad = _check_q("b1")
        bad["attrs"].pop("blockId")
        with pytest.raises(RichContentError, match="blockId"):
            validate_lesson_content(_doc(bad))

    def test_unknown_node_rejected(self):
        with pytest.raises(RichContentError):
            validate_lesson_content(_doc({"type": "iframe", "attrs": {"src": "x"}}))

    def test_base_link_protocol_still_enforced(self):
        # Базовый walker rich_content работает и внутри урока.
        bad_link = {
            "type": "paragraph",
            "content": [
                {
                    "type": "text",
                    "text": "click",
                    "marks": [{"type": "link", "attrs": {"href": "javascript:alert(1)"}}],
                }
            ],
        }
        with pytest.raises(RichContentError):
            validate_lesson_content(_doc(bad_link))

    def test_extra_node_nested_in_callout(self):
        payload = _doc(
            {
                "type": "callout",
                "attrs": {"kind": "tip"},
                "content": [_video(MEDIA)],
            }
        )
        assert validate_lesson_content(payload)


class TestCollectors:
    def test_gate_blocks_only_gated(self):
        payload = _doc(_check_q("g1", gate=True), _check_q("q2"), _check_q("g3", gate=True))
        assert collect_gate_blocks(payload) == ["g1", "g3"]

    def test_required_videos_only_flagged(self):
        other = str(uuid4())
        payload = _doc(_video(MEDIA, require=True), _video(other))
        assert collect_required_videos(payload) == [MEDIA]

    def test_media_ids_from_gallery_and_figure(self):
        g1, g2, f1 = str(uuid4()), str(uuid4()), str(uuid4())
        payload = _doc(
            {"type": "figure", "attrs": {"mediaId": f1}},
            {"type": "gallery", "attrs": {"items": [{"mediaId": g1}, {"mediaId": g2}]}},
        )
        assert collect_media_ids(payload) == {f1, g1, g2}


class TestCheckAnswer:
    def test_correct(self):
        assert check_answer(_doc(_check_q("b1", correct=1)), "b1", 1) is True

    def test_wrong(self):
        assert check_answer(_doc(_check_q("b1", correct=1)), "b1", 2) is False

    def test_missing_block(self):
        assert check_answer(_doc(_check_q("b1")), "nope", 1) is None


class TestPrepareForConsumer:
    def _sign(self, media_id: UUID) -> str:
        return f"/signed/{media_id}"

    def test_media_signed(self):
        payload = _doc(_video(MEDIA), {"type": "figure", "attrs": {"mediaId": MEDIA}})
        out = prepare_for_consumer(payload, self._sign)
        nodes = out["doc"]["content"]
        assert nodes[0]["attrs"]["src"] == f"/signed/{MEDIA}"
        assert nodes[1]["attrs"]["src"] == f"/signed/{MEDIA}"

    def test_gallery_items_signed(self):
        payload = _doc({"type": "gallery", "attrs": {"items": [{"mediaId": MEDIA}]}})
        out = prepare_for_consumer(payload, self._sign)
        assert out["doc"]["content"][0]["attrs"]["items"][0]["src"] == f"/signed/{MEDIA}"

    def test_correct_stripped(self):
        out = prepare_for_consumer(_doc(_check_q("b1", correct=2)), self._sign)
        attrs = out["doc"]["content"][0]["attrs"]
        assert "correct" not in attrs
        assert attrs["blockId"] == "b1"

    def test_editor_mode_keeps_correct(self):
        out = prepare_for_consumer(
            _doc(_check_q("b1", correct=2)), self._sign, strip_correct=False
        )
        assert out["doc"]["content"][0]["attrs"]["correct"] == 2

    def test_original_not_mutated(self):
        payload = _doc(_check_q("b1", correct=2))
        prepare_for_consumer(payload, self._sign)
        assert payload["doc"]["content"][0]["attrs"]["correct"] == 2

"""Обработка контента урока (Ф3a): валидация, обогащение, гейты. Pure.

Ноды урока сверх текстового набора rich_content:
- figure  {mediaId, caption?, lightbox?}
- gallery {items: [{mediaId, caption?}], mode: steps|compare}
- video   {mediaId, requireFullWatch?, disableSeek?}
- pdfEmbed {mediaId, forbidDownload?}
- surveyEmbed {surveyId}
- checkQuestion {blockId, question, options: [...], correct: int, gateNext?}

Перед отдачей потребителю:
- media-нодам добавляется attrs.src (подписанный URL);
- у checkQuestion ВЫРЕЗАЕТСЯ attrs.correct (ответ проверяет сервер).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from copy import deepcopy
from typing import Any
from uuid import UUID

from app.services.rich_content import (
    NEWS_NODES,
    RichContentError,
    _walk,  # noqa: PLC2701 — общий walker валидатора
)

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)

LESSON_EXTRA_NODES = frozenset(
    {"figure", "gallery", "video", "pdfEmbed", "surveyEmbed", "checkQuestion"}
)
LESSON_NODES = NEWS_NODES | LESSON_EXTRA_NODES

MAX_BYTES_LESSON = 2_000_000


def _is_uuid(value: Any) -> bool:
    return isinstance(value, str) and bool(_UUID_RE.match(value))


def _validate_extra_node(node: dict[str, Any]) -> None:
    ntype = node.get("type")
    attrs = node.get("attrs") or {}
    if ntype in ("figure", "video", "pdfEmbed"):
        if not _is_uuid(attrs.get("mediaId")):
            raise RichContentError(f"{ntype}: некорректный mediaId")
    elif ntype == "gallery":
        items = attrs.get("items")
        if not isinstance(items, list) or not (1 <= len(items) <= 20):
            raise RichContentError("gallery: 1..20 изображений")
        for item in items:
            if not isinstance(item, dict) or not _is_uuid(item.get("mediaId")):
                raise RichContentError("gallery: некорректный mediaId")
    elif ntype == "surveyEmbed":
        if not _is_uuid(attrs.get("surveyId")):
            raise RichContentError("surveyEmbed: некорректный surveyId")
    elif ntype == "checkQuestion":
        if not isinstance(attrs.get("blockId"), str) or not attrs["blockId"]:
            raise RichContentError("checkQuestion: нужен blockId")
        question = attrs.get("question")
        options = attrs.get("options")
        correct = attrs.get("correct")
        if not isinstance(question, str) or not question.strip():
            raise RichContentError("checkQuestion: пустой вопрос")
        if not isinstance(options, list) or not (2 <= len(options) <= 10):
            raise RichContentError("checkQuestion: 2..10 вариантов")
        if not isinstance(correct, int) or not 0 <= correct < len(options):
            raise RichContentError("checkQuestion: correct вне диапазона")


def validate_lesson_content(payload: Any) -> dict[str, Any]:
    """Валидация {schema:1, doc} с расширенным набором нод урока."""
    import json

    if not isinstance(payload, dict) or payload.get("schema") != 1:
        raise RichContentError("ожидается {schema: 1, doc: {...}}")
    doc = payload.get("doc")
    if not isinstance(doc, dict) or doc.get("type") != "doc":
        raise RichContentError("doc: корневая нода должна быть type=doc")
    if len(json.dumps(payload, ensure_ascii=False).encode()) > MAX_BYTES_LESSON:
        raise RichContentError("урок больше лимита 2 МБ")

    # Двухпроходно: общий walker пропускает extra-ноды (attrs не знает) —
    # для них своя проверка, а walker зовём с расширенным whitelist'ом,
    # перехватывая исключения по attrs extra-нод.
    def check(node: dict[str, Any]) -> None:
        if node.get("type") in LESSON_EXTRA_NODES:
            _validate_extra_node(node)
        for child in node.get("content") or []:
            if isinstance(child, dict):
                check(child)

    check(doc)
    _walk_with_extras(doc)
    return payload


def _walk_with_extras(doc: dict[str, Any]) -> None:
    """rich_content._walk, но extra-ноды урока проверяются локально."""

    def strip_extras(node: dict[str, Any]) -> dict[str, Any]:
        if node.get("type") in LESSON_EXTRA_NODES:
            # Подменяем на пустой параграф для базового walker'а.
            return {"type": "paragraph"}
        out = dict(node)
        if node.get("content"):
            out["content"] = [
                strip_extras(c) for c in node["content"] if isinstance(c, dict)
            ]
        return out

    _walk(strip_extras(doc), NEWS_NODES, 0)


def transform_nodes(
    payload: dict[str, Any], fn: Callable[[dict[str, Any]], dict[str, Any] | None]
) -> dict[str, Any]:
    """Копия payload с fn(node)→node для каждой ноды (None = без изменений)."""
    result = deepcopy(payload)

    def walk(node: dict[str, Any]) -> None:
        replaced = fn(node)
        if replaced is not None:
            node.clear()
            node.update(replaced)
        for child in node.get("content") or []:
            if isinstance(child, dict):
                walk(child)

    doc = result.get("doc")
    if isinstance(doc, dict):
        walk(doc)
    return result


def collect_media_ids(payload: dict[str, Any]) -> set[str]:
    found: set[str] = set()

    def fn(node: dict[str, Any]) -> None:
        attrs = node.get("attrs") or {}
        if node.get("type") in ("figure", "video", "pdfEmbed") and _is_uuid(
            attrs.get("mediaId")
        ):
            found.add(attrs["mediaId"])
        if node.get("type") == "gallery":
            for item in attrs.get("items") or []:
                if isinstance(item, dict) and _is_uuid(item.get("mediaId")):
                    found.add(item["mediaId"])
        return

    transform_nodes(payload, fn)
    return found


def collect_gate_blocks(payload: dict[str, Any]) -> list[str]:
    """block_id всех checkQuestion с gateNext=true."""
    gates: list[str] = []

    def fn(node: dict[str, Any]) -> None:
        attrs = node.get("attrs") or {}
        if node.get("type") == "checkQuestion" and attrs.get("gateNext"):
            gates.append(str(attrs.get("blockId")))
        return

    transform_nodes(payload, fn)
    return gates


def collect_required_videos(payload: dict[str, Any]) -> list[str]:
    required: list[str] = []

    def fn(node: dict[str, Any]) -> None:
        attrs = node.get("attrs") or {}
        if (
            node.get("type") == "video"
            and attrs.get("requireFullWatch")
            and _is_uuid(attrs.get("mediaId"))
        ):
            required.append(attrs["mediaId"])
        return

    transform_nodes(payload, fn)
    return required


def check_answer(payload: dict[str, Any], block_id: str, answer: int) -> bool | None:
    """Проверить ответ checkQuestion. None — блок не найден."""
    result: dict[str, bool] = {}

    def fn(node: dict[str, Any]) -> None:
        attrs = node.get("attrs") or {}
        if node.get("type") == "checkQuestion" and attrs.get("blockId") == block_id:
            result["ok"] = attrs.get("correct") == answer
        return

    transform_nodes(payload, fn)
    return result.get("ok")


def collect_survey_ids(payload: dict[str, Any] | None) -> set[str]:
    """surveyId всех встроенных опросов — чтобы взять их размер одним запросом."""
    if not payload:
        return set()
    ids: set[str] = set()

    def fn(node: dict[str, Any]) -> None:
        attrs = node.get("attrs") or {}
        if node.get("type") == "surveyEmbed" and _is_uuid(attrs.get("surveyId")):
            ids.add(attrs["surveyId"])
        return

    transform_nodes(payload, fn)
    return ids


def prepare_for_consumer(
    payload: dict[str, Any],
    sign: Callable[[UUID], str],
    *,
    strip_correct: bool = True,
    survey_counts: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Подписанные URL в media-нодах + вырезанный correct у checkQuestion.

    strip_correct=False — режим редактора (author/publisher): подписи src
    нужны для превью, но правильный ответ остаётся в контенте.

    survey_counts: surveyId → число вопросов, чтобы карточка опроса обещала
    «3 вопроса», а не отправляла в неизвестность. Значение вычисляется на
    каждой отдаче, поэтому осевшая в контенте копия устареть не может — как
    и подписанный src, она перезаписывается при чтении.
    """

    def fn(node: dict[str, Any]) -> dict[str, Any] | None:
        ntype = node.get("type")
        attrs = dict(node.get("attrs") or {})
        if ntype in ("figure", "video", "pdfEmbed") and _is_uuid(attrs.get("mediaId")):
            attrs["src"] = sign(UUID(attrs["mediaId"]))
            return {**node, "attrs": attrs}
        if ntype == "gallery":
            items = []
            for item in attrs.get("items") or []:
                if isinstance(item, dict) and _is_uuid(item.get("mediaId")):
                    items.append({**item, "src": sign(UUID(item["mediaId"]))})
                else:
                    items.append(item)
            attrs["items"] = items
            return {**node, "attrs": attrs}
        if ntype == "surveyEmbed" and survey_counts is not None:
            count = survey_counts.get(str(attrs.get("surveyId")))
            if count is not None:
                attrs["questionCount"] = count
                return {**node, "attrs": attrs}
            return None
        if ntype == "checkQuestion" and strip_correct:
            attrs.pop("correct", None)
            return {**node, "attrs": attrs}
        return None

    return transform_nodes(payload, fn)


def extract_lesson_text(payload: dict[str, Any]) -> str:
    from app.services.rich_content import extract_text

    return extract_text(payload)


# Скорость чтения ~180 слов/мин при средней длине русского слова с пробелом
# ~6 знаков; иллюстрация добавляет 10 секунд на разглядывание. Оценка нужна
# только как ориентир в шапке урока — точность до минуты избыточна.
_CHARS_PER_MINUTE = 1080
_SECONDS_PER_IMAGE = 10


def minutes_from_chars(chars: int, images: int = 0) -> int:
    """Минуты чтения по объёму текста — общая формула для Python и SQL.

    Списку курсов грузить контент всех уроков незачем: он берёт длину текста
    агрегатом в Postgres (jsonb_path_query_array по всем .text) и приводит её
    сюда. Оценка «~», поэтому расхождение в служебные кавычки не важно.
    """
    seconds = chars / _CHARS_PER_MINUTE * 60 + images * _SECONDS_PER_IMAGE
    return max(1, round(seconds / 60))


def estimate_reading_minutes(payload: dict[str, Any] | None) -> int:
    """Минуты чтения урока. Пустой урок — 1 минута, не 0."""
    if not payload:
        return 1
    text = extract_lesson_text(payload)
    images = 0

    def fn(node: dict[str, Any]) -> None:
        nonlocal images
        if node.get("type") == "figure":
            images += 1
        elif node.get("type") == "gallery":
            items = (node.get("attrs") or {}).get("items")
            images += len(items) if isinstance(items, list) else 0

    transform_nodes(payload, fn)
    return minutes_from_chars(len(text), images)


def has_check_question(payload: dict[str, Any] | None) -> bool:
    """Есть ли в уроке контрольный вопрос — для меты в списке уроков.

    Считаются ВСЕ checkQuestion, а не только гейтящие: в строке урока мета
    обещает вопрос по ходу чтения, а не предусловие завершения.
    """
    if not payload:
        return False
    found: list[bool] = []

    def fn(node: dict[str, Any]) -> None:
        if node.get("type") == "checkQuestion":
            found.append(True)
        return

    transform_nodes(payload, fn)
    return bool(found)

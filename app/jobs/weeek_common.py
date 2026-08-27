"""Общее для обоих проходов переноса из WEEEK.

Два прохода разнесены во времени на недели: первый заводит задачи, второй
доставляет исполнителей, когда люди наконец зайдут в Hub. Связывает их не
файл-карта (её легко потерять), а **детерминированный id**: строка в Hub
вычисляется из id объекта в WEEEK и тенанта.

Это же даёт идемпотентность и возобновление после падения — состояние живёт
в самой базе, а не в отдельном файле, который может с ней разъехаться.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from uuid import UUID, uuid5

# Сгенерирован один раз и прибит гвоздями: поменять его — значит потерять
# связь со всем, что уже перенесено.
WEEEK_NS = UUID("d3f2d640-0c0f-4b97-a33d-8664b5e61830")

KIND_FOLDER = "folder"
KIND_PROJECT = "project"
KIND_STAGE = "stage"
KIND_SECTION = "section"
KIND_TASK = "task"
KIND_ATTACHMENT = "attachment"
KIND_CUSTOM_FIELD = "cfd"

# Потолок `TaskCreate.description`. Сервер обязан отдавать значение, которое
# сам же примет обратно: иначе первая правка описания в UI получит 422.
DESCRIPTION_MAX = 20_000

_PROVENANCE = "Перенесено из WEEEK (задача {weeek_id})."
_ASSIGNEE_RE = re.compile(r"\n*_Исполнител[ья] в WEEEK: [^\n]*_[ \t]*$")


def hub_id(tenant_id: UUID, kind: str, weeek_key: str | int) -> UUID:
    """Стабильный id строки в Hub по её происхождению в WEEEK.

    `tenant_id` в ключе не для красоты: staging и прод держат ОДИН и тот же
    тенант uppetit в разных базах, а вот тестовый `uppetit-staging` — другой,
    и id не должны пересекаться между ними.
    """
    return uuid5(WEEEK_NS, f"{tenant_id}:{kind}:{weeek_key}")


def assignee_note(names: Sequence[str]) -> str | None:
    """«Исполнитель в WEEEK: …» — строка для тех, кого в Hub ещё нет.

    Курсив, а не жирный: это сноска, а не часть задачи. Проход 2 снимает её
    ровно по этому шаблону, поэтому формат менять нельзя, не поправив
    `_ASSIGNEE_RE`.
    """
    clean = [re.sub(r"[_\n]+", " ", n).strip() for n in names if n and n.strip()]
    if not clean:
        return None
    word = "Исполнитель" if len(clean) == 1 else "Исполнители"
    return f"_{word} в WEEEK: {', '.join(clean)}_"


def compose_description(
    body: str | None,
    *,
    weeek_id: int,
    parent_note: str | None = None,
    attachments_note: str | None = None,
    assignee_note_text: str | None = None,
) -> str | None:
    """Описание задачи целиком: текст плюс блок «что не доехало».

    Блок появляется ТОЛЬКО когда что-то действительно потеряно — у 13 тысяч
    задач из 16 703 описание остаётся ровно таким, каким было в WEEEK.
    Строка исполнителя всегда последняя: проход 2 снимает её с хвоста, не
    трогая остального.
    """
    notes = [n for n in (parent_note, attachments_note, assignee_note_text) if n]
    if not notes:
        return body
    block = "\n".join([_PROVENANCE.format(weeek_id=weeek_id), *notes])
    tail = f"---\n{block}"
    head = (body or "").rstrip()
    budget = DESCRIPTION_MAX - len(tail) - 2
    if len(head) > budget:
        cut = head.rfind("\n\n", 0, budget)
        head = (head[:cut] if cut > budget // 2 else head[:budget]).rstrip()
    return f"{head}\n\n{tail}" if head else tail


def strip_assignee_note(text: str | None) -> tuple[str | None, bool]:
    """Снять строку «Исполнитель в WEEEK: …» с хвоста. Идемпотентна.

    Возвращает (текст, сняли ли). Если строки нет — текст не трогаем вовсе:
    человек мог переписать описание, и хирургия важнее чистоты.
    """
    if not text:
        return text, False
    stripped = _ASSIGNEE_RE.sub("", text)
    if stripped == text:
        return text, False
    return stripped.rstrip() or None, True


def notes_for(row: dict, tenant_id: UUID) -> tuple[str | None, str | None]:
    """(строка про родителя, строка про вложения) для одной задачи бандла.

    Живёт здесь, а не в импортёре: проход 2 обязан собрать РОВНО ту же
    строку, иначе он не узнает описание, которое сам же и записал, и не
    рискнёт снимать сноску об исполнителе.
    """
    parent_note = None
    ref = row.get("parent_ref")
    if ref:
        title = (ref.get("title") or "задача").strip()
        if ref["kind"] == "orphan":
            parent_note = f"Подзадача задачи «{title}» — родитель не перенесён."
        else:
            target = hub_id(tenant_id, KIND_TASK, ref["weeek_id"])
            project = hub_id(tenant_id, KIND_PROJECT, ref["project_weeek_id"])
            prefix = (
                "Подзадача задачи"
                if ref["kind"] == "cross_project"
                else "В WEEEK была подзадачей задачи"
            )
            parent_note = f"{prefix} «{title}» — [открыть](/projects/{project}?task={target})."
    names = row.get("attachment_names_only") or []
    attachments_note = f"Вложения в WEEEK: {', '.join(names)}." if names else None
    return parent_note, attachments_note

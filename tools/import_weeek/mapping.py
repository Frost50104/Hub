"""Чистый маппинг WEEEK → Hub. Ни сети, ни БД — только данные.

Всё, что здесь считается, попадает в bundle и потом просто записывается
джобой. Отсюда требование к каждой функции: детерминизм. Два прогона
сборщика на одних и тех же ответах API обязаны дать одинаковые `seq`,
позиции и ключи — иначе повторный импорт переставит карточки.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

from app.services.timefmt import display_tz

# ─── Приоритет ──────────────────────────────────────────────────────────────

# WEEEK хранит 0..3, Hub — строки. Шкала подтверждена содержанием задач:
# у приоритета 3 — «СЕГОДНЯ ВЕРН С ВАР ТОЧЕК…», у 0 — «макет в штендер».
# `None` (98% задач) → medium: это и дефолт Hub.
PRIORITY_MAP: dict[int, str] = {0: "low", 1: "medium", 2: "high", 3: "urgent"}


def priority_of(raw: object) -> str:
    if isinstance(raw, bool) or not isinstance(raw, int):
        return "medium"
    return PRIORITY_MAP.get(raw, "medium")


# ─── Ключ проекта ───────────────────────────────────────────────────────────

# Транслит ОБОИХ регистров. `project_key.generate_unique_key` этого не умеет
# (translate идёт до .upper(), см. docs/tech-debt/open.md), и «Дизайн» там
# превращается в ключ `D`.
_CYRILLIC: dict[str, str] = {
    "а": "A", "б": "B", "в": "V", "г": "G", "д": "D", "е": "E", "ё": "E",
    "ж": "ZH", "з": "Z", "и": "I", "й": "Y", "к": "K", "л": "L", "м": "M",
    "н": "N", "о": "O", "п": "P", "р": "R", "с": "S", "т": "T", "у": "U",
    "ф": "F", "х": "H", "ц": "C", "ч": "CH", "ш": "SH", "щ": "SCH", "ъ": "",
    "ы": "Y", "ь": "", "э": "E", "ю": "YU", "я": "YA",
}
# Предлоги и союзы не несут смысла в аббревиатуре: «Поход на кофе» → PK, не PNK.
_STOP_WORDS = frozenset(
    {"и", "в", "во", "на", "по", "для", "с", "со", "о", "об", "от", "до", "у", "за"}
)
_KEY_FALLBACK = "PROJ"
# Потолок 12, хотя колонка допускает 32: `_TASK_KEY_RE` ассистента принимает
# {1,16} символов, и ключ с суффиксом коллизии должен в него влезать, иначе
# «PLP-42» перестанет находиться.
KEY_MAX_LEN = 12


def translit(text: str) -> str:
    """Кириллица → латиница, остальное — как есть; не-буквенно-цифровое → пробел."""
    out: list[str] = []
    for ch in text:
        low = ch.lower()
        if low in _CYRILLIC:
            out.append(_CYRILLIC[low])
        elif ch.isascii() and ch.isalnum():
            out.append(ch)
        else:
            out.append(" ")
    return re.sub(r"\s+", " ", "".join(out)).strip().upper()


def key_hint(name: str) -> str:
    """Кандидат в ключ проекта. Коллизии разрешает джоба — она видит тенант."""
    # Стоп-слова отсеиваются ДО транслита: после него «на» это уже «NA», и
    # сравнение с русским списком молча ничего не находило бы.
    raw_words = [w for w in re.split(r"[^\w]+", name, flags=re.UNICODE) if w]
    kept = [w for w in raw_words if w.casefold() not in _STOP_WORDS] or raw_words
    significant = [w for w in (translit(w) for w in kept) if w]
    if len(significant) >= 2:
        initials = "".join(w[0] for w in significant if w[0].isalpha())[:4]
        if len(initials) >= 2:
            return initials
    if not significant:
        return _KEY_FALLBACK
    single = re.sub(r"^[^A-Z]+", "", significant[0])[:KEY_MAX_LEN - 4]
    return single or _KEY_FALLBACK


# ─── Этапы и секции ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class StageSpec:
    key: str          # нормализованное имя — стабильный идентификатор этапа
    name: str         # что видит человек
    position: int


@dataclass(frozen=True)
class SectionSpec:
    board_id: int
    name: str
    position: int


# Задачи, у которых в WEEEK колонки не было вовсе (38% объёма), приезжают
# БЕЗ статуса: `stage_key: null` → `tasks.stage_id IS NULL` (0046). Они есть
# в списке, календаре и поиске, но не на доске. Синтетической колонки-приёмника
# нет намеренно: имя колонки читают глазами и верят ему.


def normalize_stage_name(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip()).casefold()


def merge_stages(boards: list[dict]) -> tuple[list[StageSpec], dict[int, str]]:
    """Колонки всех досок проекта → общий набор этапов.

    Возвращает (этапы по позициям, {id колонки WEEEK: ключ этапа}). Слияние по
    нормализованному имени: у 12 из 13 досок «Ввод/вывод сотрудников» колонки
    одинаковые, и без слияния проект получил бы 39 колонок вместо 20.
    Отображаемое имя — первое написание группы (порядок досок стабилен).
    """
    order: list[str] = []
    display: dict[str, str] = {}
    by_column: dict[int, str] = {}
    for board in boards:
        for column in board.get("columns") or []:
            key = normalize_stage_name(column.get("name", ""))
            if not key:
                continue
            if key not in display:
                display[key] = re.sub(r"\s+", " ", column["name"].strip())
                order.append(key)
            by_column[int(column["id"])] = key
    stages = [StageSpec(key=k, name=display[k], position=i) for i, k in enumerate(order)]
    return stages, by_column


def merge_sections(boards: list[dict]) -> list[SectionSpec]:
    """Доска → секция, но ТОЛЬКО если досок больше одной.

    У 42 проектов из 47 доска называется как сам проект — секция была бы шумом.
    """
    if len(boards) < 2:
        return []
    return [
        SectionSpec(board_id=int(b["id"]), name=(b.get("name") or "").strip()[:255], position=i)
        for i, b in enumerate(boards)
    ]


# ─── Портфели → папки ───────────────────────────────────────────────────────


def root_portfolio(portfolios: dict[int, dict], portfolio_id: int | None) -> dict | None:
    """Подняться до корня: папки в Hub — ровно один уровень."""
    seen: set[int] = set()
    current = portfolio_id
    while current is not None and current in portfolios and current not in seen:
        seen.add(current)
        parent = portfolios[current].get("parentId")
        if parent is None:
            return portfolios[current]
        current = parent
    return portfolios.get(current) if current in portfolios else None


# ─── Даты ───────────────────────────────────────────────────────────────────


def _day_from_iso_instant(raw: str) -> date | None:
    try:
        moment = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment.astimezone(display_tz()).date()


def day_of(raw_date: str | None, raw_datetime: str | None) -> date | None:
    """Календарный день срока/старта. В Hub время суток не хранится вовсе.

    `dueDate` уже день — берём как есть. `dueDateTime` переводим в display tz
    и берём день ТАМ: воркспейс WEEEK стоит в Europe/Podgorica, а люди и Hub
    живут в Москве, и наивный разбор сдвинул бы часть сроков на сутки.
    """
    if raw_date:
        try:
            return date.fromisoformat(raw_date[:10])
        except ValueError:
            pass
    if raw_datetime:
        return _day_from_iso_instant(raw_datetime)
    return None


def instant_of(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


# ─── Подзадачи ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ParentDecision:
    """Что делать с `parentId` конкретной задачи."""

    parent_weeek_id: int | None      # связь в Hub (None — задача верхнего уровня)
    note_ref: int | None             # про кого написать в описании
    note_kind: str | None            # "cross_project" | "orphan" | "flattened"


_KEEP = ParentDecision(None, None, None)


def resolve_parents(
    tasks: dict[int, dict], in_scope: set[int]
) -> dict[int, ParentDecision]:
    """Одноуровневая иерархия Hub из произвольного дерева WEEEK.

    Четыре случая:
    - родитель в объёме, в том же проекте, сам верхнего уровня → связь как есть;
    - глубина 2+ → перевешиваем на КОРЕНЬ ветки (прямой родитель сам может быть
      подзадачей, а `assert_parent_one_level` это запрещает), про промежуточное
      звено пишем в описание;
    - родитель в другом проекте → связи НЕТ. Доска фильтрует `!parent_task_id`,
      а список подзадач собирается из задач того же проекта: ребёнок в чужом
      проекте исчез бы и с доски, и из карточки родителя;
    - родитель не перенесён → связи нет, строка в описание.
    """
    out: dict[int, ParentDecision] = {}
    for task_id in tasks:
        raw_parent = tasks[task_id].get("parentId")
        if raw_parent is None:
            out[task_id] = _KEEP
            continue
        parent_id = int(raw_parent)
        if parent_id not in tasks or parent_id not in in_scope:
            out[task_id] = ParentDecision(None, parent_id, "orphan")
            continue
        root_id, depth = _root_of(tasks, parent_id)
        if tasks[root_id].get("projectId") != tasks[task_id].get("projectId"):
            out[task_id] = ParentDecision(None, parent_id, "cross_project")
        elif root_id not in in_scope:
            out[task_id] = ParentDecision(None, parent_id, "orphan")
        elif depth == 0:
            out[task_id] = ParentDecision(root_id, None, None)
        else:
            out[task_id] = ParentDecision(root_id, parent_id, "flattened")
    return out


def _root_of(tasks: dict[int, dict], task_id: int) -> tuple[int, int]:
    """(корень ветки, сколько шагов до него). Циклы обрываются на себе."""
    seen: set[int] = set()
    current, depth = task_id, 0
    while True:
        parent = tasks[current].get("parentId")
        if parent is None or int(parent) not in tasks or int(parent) in seen:
            return current, depth
        seen.add(current)
        current, depth = int(parent), depth + 1


# ─── Порядок задач ──────────────────────────────────────────────────────────


def task_sort_key(task: dict) -> tuple[str, int]:
    """Стабильный порядок: по дате создания, при равенстве — по id WEEEK."""
    return (task.get("createdAt") or "", int(task["id"]))


# ─── Объём переноса ─────────────────────────────────────────────────────────

# Решение владельца: переносим проекты, в которых заводили задачи в 2026 году.
# 47 проектов из 149 и 16 703 задачи из 51 007 — остальное либо мертво, либо
# лежит в проектах, которых API уже не отдаёт.
SCOPE_SINCE = "2026-01-01"


def select_projects(
    projects: list[dict], tasks: list[dict], *, since: str = SCOPE_SINCE
) -> set[int]:
    """id проектов, в которых есть задача, созданная не раньше `since`."""
    known = {int(p["id"]) for p in projects}
    return {
        int(t["projectId"])
        for t in tasks
        if t.get("projectId") is not None
        and int(t["projectId"]) in known
        and (t.get("createdAt") or "") >= since
    }


def select_tasks(tasks: list[dict], project_ids: set[int]) -> list[dict]:
    """Задачи объёма. Помеченные удалёнными не переносим — в WEEEK они уже
    в корзине, и воспроизводить корзину в Hub незачем."""
    return [
        t
        for t in tasks
        if t.get("projectId") is not None
        and int(t["projectId"]) in project_ids
        and not t.get("isDeleted")
    ]

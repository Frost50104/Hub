"""Pydantic schemas for Project + ProjectMember endpoints."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

ProjectRole = Literal["owner", "editor", "viewer"]

# Бейдж проекта: один эмодзи ЛИБО картинка, иначе — две буквы ключа.
#
# Grapheme clustering в stdlib нет, а тянуть `regex`/`emoji` в зависимости ради
# одного поля — плохая сделка (список в pyproject намеренно короткий). Поэтому
# проверяем ФОРМУ кластера регуляркой на `re`.
#
# Из диапазона пиктографов НАМЕРЕННО вырезаны две группы, у каждой своё правило
# ниже: U+1F1E6..U+1F1FF (regional indicators — легальны только ПАРОЙ, флаг;
# одиночный рисуется буквой в рамке) и U+1F3FB..U+1F3FF (модификаторы тона кожи
# — сами по себе это цветной мазок).
_PICTO = (
    "\u00a9\u00ae\u203c\u2049\u2122\u2139"
    "\u2194-\u21aa"
    "\u231a-\u231b\u2328\u23cf\u23e9-\u23f3\u23f8-\u23fa"
    "\u24c2"
    "\u25aa-\u25ab\u25b6\u25c0\u25fb-\u25fe"
    "\u2600-\u27bf"
    "\u2934-\u2935"
    "\u2b00-\u2bff"
    "\u3030\u303d\u3297\u3299"
    "\U0001f000-\U0001f1e5"
    "\U0001f200-\U0001f3fa"
    "\U0001f400-\U0001faff"
)
_RI = "[\U0001f1e6-\U0001f1ff]"
_TONE = "[\U0001f3fb-\U0001f3ff]"
_ATOM = f"[{_PICTO}]\ufe0f?{_TONE}?"  # база + VS16 + тон кожи
_KEYCAP = "[0-9#*]\ufe0f?\u20e3"  # 1️⃣ #️⃣ — цифра допустима ТОЛЬКО так
_TAGSEQ = "\U0001f3f4[\U000e0020-\U000e007e]{1,6}\U000e007f"  # флаг субдивизии
_ZWJ = f"{_ATOM}(?:\u200d{_ATOM})*"  # 👩‍💻, 👨‍👩‍👧‍👦, 🏳️‍🌈

# `\A…\Z`, а НЕ `^…$`: `$` в Python матчится и перед завершающим переводом
# строки, и "🚀\n" прошёл бы валидацию.
_ONE_EMOJI_RE = re.compile(f"\\A(?:{_TAGSEQ}|{_KEYCAP}|{_RI}{_RI}|{_ZWJ})\\Z")

BADGE_EMOJI_ERR = "Бейдж — ровно один эмодзи"
# Ровно ширина колонки projects.badge_emoji (VARCHAR считает кодпоинты).
BADGE_EMOJI_MAX_CP = 32

# Описание проекта — markdown, отдельный экран «О проекте». 4 000 знаков
# (прежний потолок) это две страницы; владелец просил «любую другую
# информацию». Колонка и так `Text`, миграции лимит не требует.
DESCRIPTION_MAX = 20_000


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    # When omitted, backend generates a unique key from `name` (initials,
    # cyrillic transliteration, collision check). Clients may pass an
    # explicit key (e.g. importing from Asana) — same format constraints.
    key: str | None = Field(
        default=None, min_length=1, max_length=32, pattern=r"^[A-Z][A-Z0-9_-]*$"
    )
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX)


class ProjectUpdate(BaseModel):
    # extra="forbid" — как у TaskCreate/TaskUpdate (0045): pydantic по
    # умолчанию молча игнорирует лишний ключ, и клиент получал бы 200 на
    # запрос, который сервер не выполнил. Вводить безопасно именно сейчас —
    # у useUpdateProject на фронте до этого релиза ноль вызывающих.
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX)


class TemplateRef(BaseModel):
    id: UUID
    name: str | None


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    key: str
    name: str
    description: str | None
    # Бейдж: эмодзи ЛИБО подписанный путь к картинке. Оба None — две буквы
    # ключа, как раньше (это фолбэк, а не «пустое состояние»). Без дефолтов по
    # образцу can_edit/can_manage: забытый call-site обязан падать на валидации.
    badge_emoji: str | None
    badge_url: str | None
    archived_at: datetime | None
    # Общая для тенанта раскладка. Без дефолта — по образцу can_edit/can_manage:
    # забытый call-site должен падать на валидации, а не молча отдавать None.
    folder_id: UUID | None
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    my_role: ProjectRole | None = None  # filled from project_members for current principal
    is_favorite: bool = False  # личное избранное текущего пользователя
    # Личное пространство сотрудника («Личное»). Отдаём производный булев, а не
    # personal_owner_id: клиенту нужен факт, чтобы не рисовать «Архивировать» и
    # «Переместить в папку» (сервер на них отвечает 409), а не «чьё это личное».
    is_personal: bool = False
    # Эффективные права вызывающего = членство ИЛИ hub:admin-байпас. Считает
    # ТОЛЬКО сервер (project_access.capabilities) — клиент их рендерит и своей
    # копии правила не заводит. Без дефолтов: забытый call-site должен падать
    # на валидации, а не молча прятать контролы.
    can_edit: bool  # задачи, импорт CSV, публичные ссылки, метки на задаче
    can_manage: bool  # имя и описание, бейдж, кастом-поля, CRUD меток, участники, архив, удаление
    # Счётчики задач для шапки проекта («N задач»), пустого фильтра
    # («Из N — ни одной») и карточки проекта на «Главной» («26 задач · 4 закрыты»).
    # Считают ТОЛЬКО list_projects и get_project. Дефолт None здесь сознателен:
    # правило «без дефолтов» защищает can_edit/can_manage от забытого call-site,
    # а девяти мутирующим ручкам (patch, archive, favorite…) счётчики не нужны —
    # платить за лишний запрос на каждое переименование незачем.
    task_count: int | None = None
    done_count: int | None = None
    # Шаблоны проектов (0060). `is_template` — клиент прячет шаринг, архив,
    # звезду, галочки и просрочку; `template_anchor_on` — точка отсчёта дат
    # шаблона; `created_from_template` — откуда создан живой проект (имя —
    # снимком: под замком живой проект шаблон не видит).
    is_template: bool = False
    template_anchor_on: date | None = None
    created_from_template: TemplateRef | None = None


class ProjectFavoriteUpdate(BaseModel):
    is_favorite: bool


class ProjectBadgeUpdate(BaseModel):
    """Тело PUT /projects/{id}/badge.

    Отдельная схема, а не поле в `ProjectUpdate`: там идиома
    `if body.x is not None`, а `emoji=None` обязан значить «сними бейдж», а не
    «не трогай». Тот же довод, что у `ProjectFolderAssign`.

    `emoji` без дефолта — ключ обязателен: «забыл прислать» не равно «сними».
    """

    model_config = ConfigDict(extra="forbid")

    emoji: str | None

    @field_validator("emoji")
    @classmethod
    def _exactly_one_emoji(cls, v: str | None) -> str | None:
        if v is None:
            return None
        # Длину проверяем ДО регулярки: ZWJ-цепочка из двух десятков
        # пиктографов форму пройдёт, но не влезет в VARCHAR(32) и упадёт в
        # Postgres ошибкой 22001 — то есть 500 вместо 422.
        if len(v) > BADGE_EMOJI_MAX_CP:
            raise ValueError(BADGE_EMOJI_ERR)
        if _ONE_EMOJI_RE.match(v) is None:
            raise ValueError(BADGE_EMOJI_ERR)
        # Никакой нормализации: NFKD эмодзи буквально уничтожает (см.
        # _sanitize_filename в app/services/attachments.py).
        return v


class ProjectFolderAssign(BaseModel):
    """Тело PUT /projects/{id}/folder. Отдельная ручка, а не поле в
    ProjectUpdate: идиома того файла — `if body.x is not None`, а folder_id=None
    обязан значить «убрать из папки». Прецедент рядом — ProjectFavoriteUpdate."""

    folder_id: UUID | None


class ProjectMemberAdd(BaseModel):
    employee_id: UUID
    role: ProjectRole


class ProjectMemberUpdate(BaseModel):
    role: ProjectRole


class ProjectMemberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    employee_id: UUID
    role: ProjectRole
    added_at: datetime
    # Enriched from shadow_users JOIN — may be null if the row was reaped.
    email: str | None = None
    full_name: str | None = None

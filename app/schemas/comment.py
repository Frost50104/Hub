"""Pydantic schemas for task comments."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# Потолок тела комментария задачи — тот же, что у описания задачи (20 000):
# один лимит на «длинный текст в задаче». Был 4 000 с MVP, и отчёт на 9 279
# символов не уходил вовсе (ОС 21.09). Зеркала: ассистент импортирует эту
# константу (`assistant/tools.py::CommentArgs`, `assistant/plans.py::PlanPatch`),
# клиент держит копию `web/src/lib/commentDraft.ts::COMMENT_MAX_LENGTH`.
COMMENT_MAX_LENGTH = 20_000


class CommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=COMMENT_MAX_LENGTH)


class CommentUpdate(BaseModel):
    body: str = Field(min_length=1, max_length=COMMENT_MAX_LENGTH)


class CommentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    task_id: UUID
    author_id: UUID
    body: str
    mentioned_ids: list[UUID]
    edited_at: datetime | None
    created_at: datetime
    # Enriched via JOIN shadow_users.
    author_email: str | None = None
    author_full_name: str | None = None
    # Токен упоминания → текущее ФИО: чип рисует имя, а не логин почты.
    # Считает сервер одним батчем на список — клиент словарь не собирает
    # (раньше собирал из первых 10 сотрудников по алфавиту и врал остальным).
    mention_names: dict[str, str] = {}

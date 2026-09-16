"""Pydantic-схемы HR-профилей сотрудников (Ф0 LMS)."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

ORG_ROLE_PATTERN = "^(employee|tu|franchisee_owner|office)$"
CONTENT_ROLE_PATTERN = "^(none|author|publisher)$"
# Лёгкая проверка формы email (без email-validator в deps): local@domain.tld
EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class EmployeeCreate(BaseModel):
    email: str = Field(pattern=EMAIL_PATTERN, max_length=320)
    full_name: str = Field(min_length=1, max_length=255)
    phone: str | None = Field(default=None, max_length=32)
    position_id: UUID | None = None
    store_id: UUID | None = None
    department_id: UUID | None = None
    franchisee_id: UUID | None = None
    manager_profile_id: UUID | None = None
    org_role: str = Field(default="employee", pattern=ORG_ROLE_PATTERN)
    content_role: str = Field(default="none", pattern=CONTENT_ROLE_PATTERN)
    hired_at: date | None = None

    @field_validator("full_name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("ФИО не может быть пустым")
        return v


class EmployeeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str | None = Field(default=None, pattern=EMAIL_PATTERN, max_length=320)
    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    phone: str | None = Field(default=None, max_length=32)
    position_id: UUID | None = None
    store_id: UUID | None = None
    department_id: UUID | None = None
    franchisee_id: UUID | None = None
    manager_profile_id: UUID | None = None
    org_role: str | None = Field(default=None, pattern=ORG_ROLE_PATTERN)
    content_role: str | None = Field(default=None, pattern=CONTENT_ROLE_PATTERN)
    hired_at: date | None = None
    status_text: str | None = Field(default=None, max_length=160)


class ArchivedTwin(BaseModel):
    """Однофамилец по адресу: карточка в архиве с тем же email.

    Нужна как замена снятому `needs_restore`. Обычно это новый человек на
    освободившемся корпоративном ящике — всё правильно. Но тем же путём
    проходит ОШИБОЧНАЯ архивация, и без подсказки дубль появлялся бы молча.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    full_name: str
    archived_at: datetime | None


class EmployeeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    employee_id: UUID | None
    email: str
    full_name: str
    phone: str | None
    position_id: UUID | None
    store_id: UUID | None
    department_id: UUID | None
    franchisee_id: UUID | None
    manager_profile_id: UUID | None
    #: `person` | `service` — касса точки (0056). Карточка остаётся, но
    #: учеником не является и в списке сотрудников не показывается.
    account_kind: str
    org_role: str
    content_role: str
    hired_at: date | None
    status_text: str | None
    status: str
    archived_at: datetime | None
    archive_reason: str | None
    last_activity_at: datetime | None
    created_at: datetime
    # Закреплённые магазины (только для org_role=tu; заполняется в API).
    tu_store_ids: list[UUID] = []
    # Архивная карточка с тем же email. Заполняет ТОЛЬКО `get_employee` — в
    # списке это был бы лишний запрос на каждую строку ради редкой подсказки.
    archived_twin: ArchivedTwin | None = None
    # Кеш из auth (staff-sync, 0052; заполняется в API из shadow_users):
    # hub-роль (admin|member|viewer) и честный статус учётки.
    hub_role: str | None = None
    auth_state: str | None = None  # no_account|not_linked|not_logged_in|active|blocked|deleted


class InvitationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    full_name: str | None
    role: str
    expires_at: datetime | None


class EmployeeListResponse(BaseModel):
    items: list[EmployeeResponse]
    total: int
    # Когда штат последний раз синкался из auth; None = синка ещё не было
    # (auth не выкатил ручку) — фронт показывает плашку «ожидает».
    staff_synced_at: datetime | None = None
    # Непринятые приглашения с ролью hub — «добавлен, но ещё не входил».
    # Отдаются только hub-admin'у (скоуп all); остальным — пустой список.
    invitations: list[InvitationResponse] = []


class TuStoresReplace(BaseModel):
    store_ids: list[UUID] = Field(max_length=1000)


class ArchiveBody(BaseModel):
    # `auth_deleted` через API не принимаем: его ставит только deletion-sync.
    # Дефолт `manual` — то, что шлёт и новый клиент, и старые PWA-бандлы без
    # тела; он же освобождает вход, так что застрявший бандл автоматически
    # получает новое поведение.
    reason: str = Field(default="manual", pattern="^(manual|auto_inactivity)$")


class RestoreBody(BaseModel):
    # Повторный найм: привязать карточку к НОВОМУ auth-аккаунту.
    employee_id: UUID | None = None


class LinkBody(BaseModel):
    employee_id: UUID


class UnlinkedLoginResponse(BaseModel):
    """Вход в Hub без HR-карточки — экран «непривязанные входы»."""

    employee_id: UUID
    email: str
    full_name: str
    last_seen_at: datetime


class ImportReport(BaseModel):
    created: int
    skipped: int
    errors: list[str]
    dry_run: bool

"""Project + ProjectMember.

Both tables are tenant-scoped (RLS via app.tenant_id). Membership uses
in-app roles `owner | editor | viewer` — these are NOT in JWT, they're
a per-project access list inside Hub.

A project ALWAYS has at least one owner (enforced in service layer: deleting
the last owner is rejected). `created_by` references shadow_users.employee_id;
the creator is automatically added as owner in ProjectMember on creation.

`personal_owner_id` — личное пространство сотрудника («Личное»): проект скрыт
из всех списков проектов и живёт секцией на /my. Всё про него —
`app/services/personal_projects.py`.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("tenant_id", "key", name="uq_projects_tenant_key"),
        # «Ровно один личный проект на сотрудника» — БД-инвариант, а не
        # приложенческий лок: на этот индекс опирается идемпотентность
        # services/personal_projects.py::ensure_personal_project (гонка двух
        # параллельных /api/me гасится блокировкой на индексе).
        Index(
            "uq_projects_personal_owner",
            "tenant_id",
            "personal_owner_id",
            unique=True,
            postgresql_where=text("personal_owner_id IS NOT NULL"),
        ),
        # Блоб и его тип живут и умирают вместе.
        CheckConstraint(
            "(badge_storage_key IS NULL) = (badge_mime IS NULL)",
            name="ck_projects_badge_image_pair",
        ),
        # Эмодзи ИЛИ картинка. Оба NULL легально — это буквы.
        CheckConstraint(
            "NOT (badge_emoji IS NOT NULL AND badge_storage_key IS NOT NULL)",
            name="ck_projects_badge_exclusive",
        ),
        # Этот mime уходит прямо в Content-Type пользовательских байт, которые
        # отдаются INLINE в <img>. Whitelist на уровне БД значит, что даже баг
        # в ручке не сможет вернуть text/html. Цена — gif/avif позже потребуют
        # миграции; принято сознательно.
        CheckConstraint(
            "badge_mime IS NULL OR badge_mime IN "
            "('image/png', 'image/jpeg', 'image/webp')",
            name="ck_projects_badge_mime",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Следующий выдаваемый номер задачи (см. tasks._allocate_task_seq);
    # server_default нужен и старому коду в окне деплоя — не снимать.
    next_task_seq: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Бейдж проекта: эмодзи ЛИБО картинка, иначе две буквы ключа. Инварианты
    # держат CHECK'и в __table_args__, а не только код.
    #
    # `badge_storage_key` — путь ОТНОСИТЕЛЬНО attachments_root, как у
    # task_attachments.storage_key и media_files.storage_key. Имя файла несёт
    # свежий uuid на КАЖДУЮ заливку: подпись URL считается от ключа, поэтому
    # новая картинка = новый адрес, и прежние байты не остаются под тем же
    # URL в кэше браузера.
    badge_emoji: Mapped[str | None] = mapped_column(String(32), nullable=True)
    badge_storage_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    badge_mime: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Папка — ОБЩАЯ для тенанта раскладка (не персональная). SET NULL:
    # удаление папки не удаляет проект, он переезжает в «Без папки».
    folder_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("project_folders.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Личное пространство сотрудника: NULL — обычный проект, иначе — «Личное»
    # этого человека. Одна колонка кодирует и признак, и владельца: role='owner'
    # в project_members неоднозначен (владелец может позвать второго owner'а).
    # RESTRICT как у created_by: SET NULL бесшумно вывалил бы личный проект во
    # все списки, CASCADE снёс бы задачи.
    #
    # ИНВАРИАНТ: значение берётся ТОЛЬКО из principal.employee_id внутри
    # tenant-scoped сессии, никогда из тела запроса — FK-триггер Postgres
    # обходит RLS, и чужой employee_id прошёл бы проверку.
    personal_owner_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("shadow_users.employee_id", ondelete="RESTRICT"),
        nullable=True,
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("shadow_users.employee_id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        onupdate=text("now()"),
        nullable=False,
    )

    members: Mapped[list[ProjectMember]] = relationship(
        back_populates="project", cascade="all, delete-orphan", lazy="noload"
    )


class ProjectMember(Base):
    __tablename__ = "project_members"
    __table_args__ = (
        UniqueConstraint("project_id", "employee_id", name="uq_project_members_project_employee"),
        CheckConstraint(
            "role IN ('owner', 'editor', 'viewer')",
            name="ck_project_members_role",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    employee_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("shadow_users.employee_id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    # Личное избранное участника — не общий атрибут проекта.
    is_favorite: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    added_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("shadow_users.employee_id", ondelete="SET NULL"),
        nullable=True,
    )

    project: Mapped[Project] = relationship(back_populates="members", lazy="noload")

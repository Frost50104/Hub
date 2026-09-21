"""Tasks + watchers + comments + labels + activity.

Schema notes:
- `tasks.parent_task_id` — only one level deep (CHECK in migration).
- `tasks.position` is NUMERIC (LexoRank-style float for drag-reorder).
- `task_comments.mentioned_ids` is UUID[] populated by mention_parser.
- `task_activity` is append-only (no UPDATE/DELETE; events are facts).

Models declare structure, but the columns enabling each feature are populated
across phases:
- 3a: tasks CRUD + activity (created/status_changed/updated).
- 3b: canban — position reorder.
- 3c: watchers + comments + activity feed UI.
- 3d: labels + mentions.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        # `done` и `completed_at` — один факт в двух колонках; связь сторожит
        # БД, а не только код (`services/stages.py::set_done`).
        CheckConstraint(
            "done = (completed_at IS NOT NULL)", name="ck_tasks_done_completed_at"
        ),
        CheckConstraint(
            "priority IN ('low', 'medium', 'high', 'urgent')",
            name="ck_tasks_priority",
        ),
        # Номер уникален ВНУТРИ проекта. С 28.08 задачу можно перенести
        # (`services/task_move.py`), и это ограничение — причина, по которой
        # переезд ОБЯЗАН перевыдать `seq` через `allocate_task_seq` целевого
        # проекта: ссылки «PLP-118» в переписке после переноса не сходятся, и
        # цену диалог называет человеку до нажатия.
        UniqueConstraint("project_id", "seq", name="uq_tasks_project_seq"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parent_task_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    # Колонка доски (0040). NULL — «без статуса»: такая задача живёт в списке,
    # календаре и поиске, но на доске не показывается (0046). Имя колонки задаёт
    # пользователь, никакого системного смысла у неё нет — состояние задачи
    # живёт в `done`.
    # FK БЕЗ `ON DELETE SET NULL` намеренно: удаление этапа с задачами API не
    # пускает (409 + move_to), и молчаливое обнуление статуса у чужих задач было
    # бы сюрпризом. `NO ACTION` проверяется в конце оператора и переживает
    # каскад удаления проекта.
    stage_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("project_stages.id"),
        nullable=True,
    )

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Единственное состояние задачи. Колонка доски к нему отношения не имеет:
    # выполненную задачу видно там же, где она лежала (модель Asana).
    done: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    priority: Mapped[str] = mapped_column(String(16), nullable=False, server_default="medium")

    created_by: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("shadow_users.employee_id", ondelete="RESTRICT"),
        nullable=False,
    )
    start_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Задача РОДИЛАСЬ по повтору вот этой. SET NULL, а НЕ CASCADE (в отличие от
    # соседнего parent_task_id): удаление старой закрытой копии не должно
    # уносить всю живую цепочку серии.
    recurrence_parent_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="SET NULL"),
        nullable=True,
    )
    position: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    # Человекочитаемый номер в проекте («KEY-42»): выдаётся _allocate_task_seq
    # атомарным инкрементом projects.next_task_seq; дыры при rollback — норма.
    seq: Mapped[int] = mapped_column(Integer, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        onupdate=text("now()"),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Задача шаблона (0060) — денормализованное зеркало `projects.is_template`
    # для политики RLS: подзапрос к projects в политике сам шёл бы через RLS и
    # открывал бы замок. Совпадение с проектом сторожит триггер
    # `tasks_template_guard`; значение ставит `create_task_record` из проекта.
    is_template: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    # Родилась копированием шаблона — такие задачи не считаются в «Создано»
    # личной статистики (как копии по повтору), иначе проект по шаблону давал
    # бы «+1 745 создано за неделю».
    template_copy: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )


class TaskAssignee(Base):
    """Исполнители задачи — источник истины (0034).

    PK (task_id, employee_id) без суррогатного id — паттерн task_watchers /
    task_label_assignments; даёт бесплатный ON CONFLICT для идемпотентного
    upsert. `position` задаёт порядок отображения и НЕ уникален: уникальность
    ломала бы перестановку внутри одной транзакции.
    """

    __tablename__ = "task_assignees"
    __table_args__ = (
        PrimaryKeyConstraint("task_id", "employee_id", name="pk_task_assignees"),
    )

    task_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    employee_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("shadow_users.employee_id", ondelete="CASCADE"),
        nullable=False,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    assigned_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("shadow_users.employee_id", ondelete="SET NULL"),
        nullable=True,
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class TaskWatcher(Base):
    __tablename__ = "task_watchers"
    __table_args__ = (
        PrimaryKeyConstraint("task_id", "employee_id", name="pk_task_watchers"),
        CheckConstraint(
            "added_reason IN ('assignee', 'creator', 'mentioned', 'manual')",
            name="ck_task_watchers_added_reason",
        ),
    )

    task_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    employee_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("shadow_users.employee_id", ondelete="CASCADE"),
        nullable=False,
    )
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    added_reason: Mapped[str] = mapped_column(String(16), nullable=False)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class TaskComment(Base):
    __tablename__ = "task_comments"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    task_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    author_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("shadow_users.employee_id", ondelete="RESTRICT"),
        nullable=False,
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    mentioned_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), nullable=False, server_default="{}"
    )
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class TaskLabel(Base):
    __tablename__ = "task_labels"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_task_labels_project_name"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    color: Mapped[str] = mapped_column(String(16), nullable=False, server_default="#FFB200")


class TaskLabelAssignment(Base):
    __tablename__ = "task_label_assignments"
    __table_args__ = (
        PrimaryKeyConstraint("task_id", "label_id", name="pk_task_label_assignments"),
    )

    task_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    label_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("task_labels.id", ondelete="CASCADE"),
        nullable=False,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False, index=True
    )


class TaskActivity(Base):
    __tablename__ = "task_activity"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    task_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    actor_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("shadow_users.employee_id", ondelete="RESTRICT"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )



RECURRENCE_FREQS = ("day", "weekday", "week", "month")


class TaskRecurrence(Base):
    """Правило повтора ОДНОЙ задачи. Наличие строки = «задача повторяется».

    Строка — ТОКЕН, который тратится ровно один раз: порождение следующей копии
    начинается с `DELETE ... WHERE task_id = :id RETURNING ...`, и правило
    ПЕРЕЕЗЖАЕТ на копию. Отсюда идемпотентность без флагов — снять галочку и
    поставить снова нечего, токена на исходной задаче уже нет.

    `anchor` — день срока в момент установки правила, `occurrence` — сколько
    шагов сетки от него пройдено. Считать от ПРЕДЫДУЩЕЙ даты нельзя: «каждый
    месяц» от 31 января поплыл бы 31.01 → 28.02 → 28.03, а от якоря даёт
    31.01 → 28.02 → 31.03.
    """

    __tablename__ = "task_recurrences"
    __table_args__ = (
        CheckConstraint(
            "freq IN ('day', 'weekday', 'week', 'month')", name="ck_task_recurrences_freq"
        ),
        # «по будням» — готовый пресет; «каждые три будня» продукт не обещает.
        CheckConstraint(
            "freq <> 'weekday' OR step = 1", name="ck_task_recurrences_weekday_step"
        ),
        CheckConstraint("step BETWEEN 1 AND 365", name="ck_task_recurrences_step"),
        CheckConstraint("occurrence >= 0", name="ck_task_recurrences_occurrence"),
    )

    task_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True
    )
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    freq: Mapped[str] = mapped_column(String(8), nullable=False)
    # Колонка называется `step`, а не `interval`: INTERVAL — тип и зарезервированное
    # слово Postgres, и любой ручной SQL пришлось бы писать с кавычками.
    step: Mapped[int] = mapped_column(Integer, server_default=text("1"), nullable=False)
    anchor: Mapped[date] = mapped_column(Date, nullable=False)
    occurrence: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    created_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("shadow_users.employee_id", ondelete="SET NULL"),
        nullable=True,
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

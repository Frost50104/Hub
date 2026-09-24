"""Pydantic schemas for Task endpoints (Hub-MVP.3a)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

TaskPriority = Literal["low", "medium", "high", "urgent"]

# Четырёх системных статусов больше нет (0044): колонка доски — это имя,
# состояние задачи — `done`. Текст 422 для старых бандлов: им отвечают
# query-ловушка `reject_legacy_status` (списки) и обработчик лишних полей тела
# в `app/main.py`. Молча игнорировать legacy нельзя — старый бандл получил бы
# успешный no-op, «задача закрыта» на экране при незакрытой в базе.
LEGACY_STATUS_DETAIL = (
    "Статусы задач заменены на «выполнена / не выполнена», а этап — "
    "это колонка доски. Обновите страницу."
)


# Потолок фан-аута уведомлений (dispatch делает SELECT prefs + INSERT на
# получателя) и разумный предел для стека аватаров в UI. Живёт в схемах, а не
# в сервисе: сервис импортирует AssigneeBrief отсюда — обратный импорт дал бы
# цикл.
MAX_ASSIGNEES = 10


def dedupe(ids: Sequence[UUID]) -> list[UUID]:
    """Убрать дубли, сохранив порядок первого вхождения."""
    seen: set[UUID] = set()
    out: list[UUID] = []
    for i in ids:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


class AssigneeBrief(BaseModel):
    """Minimal assignee info, enriched via shadow_users JOIN."""

    model_config = ConfigDict(from_attributes=True)

    employee_id: UUID
    email: str | None
    full_name: str | None


class TaskCreate(BaseModel):
    # Лишнее поле = 422, а не тихое игнорирование (0045). Обратная сторона:
    # клиент обязан слать РОВНО объявленный набор — `mutate({...task})` со
    # спредом целой задачи теперь ошибка. Текст ответа собирает обработчик
    # `RequestValidationError` в `app/main.py`.
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=20_000)
    parent_task_id: UUID | None = None
    # Колонка доски; без неё задача уходит в первую по позиции. Снять статус
    # можно только правкой (PATCH с явным null) — создавать задачу сразу вне
    # доски незачем.
    stage_id: UUID | None = None
    priority: TaskPriority = "medium"
    # DEPRECATED-вход: держим ради PWA-бандлов, которые живут днями после
    # деплоя (registerType: 'prompt'). Разрешение конфликта — resolve_assignee_ids.
    assignee_id: UUID | None = None
    assignee_ids: list[UUID] | None = Field(default=None, max_length=MAX_ASSIGNEES)
    start_at: datetime | None = None
    due_at: datetime | None = None
    # Задано ли у даты время (0061). Не пришло — день, как у старых клиентов;
    # правило пары — `taskdates.resolve_date_patch`.
    start_has_time: bool | None = None
    due_has_time: bool | None = None


class TaskUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")  # см. TaskCreate

    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=20_000)
    # Явный null снимает статус: задача уходит с доски, оставаясь в списке
    # (0046). Отличить «не передали» от «передали null» — `model_fields_set`.
    stage_id: UUID | None = None
    # Состояние задачи — независимая ось: галочку ставят из любой колонки.
    done: bool | None = None
    priority: TaskPriority | None = None
    assignee_id: UUID | None = None  # DEPRECATED-вход, см. TaskCreate
    assignee_ids: list[UUID] | None = Field(default=None, max_length=MAX_ASSIGNEES)
    start_at: datetime | None = None
    due_at: datetime | None = None
    # Флаг времени передаётся ТОЛЬКО вместе со своей датой (иначе 422 из
    # ручки); дата без флага = день. См. `taskdates.resolve_date_patch`.
    start_has_time: bool | None = None
    due_has_time: bool | None = None
    position: Decimal | None = None
    # Для nullable-полей (assignee_id/start_at/due_at) endpoint
    # различает «поле не пришло» (нет в model_fields_set → не трогаем) и
    # «пришёл явный null» (очистить значение). Не-nullable поля (title/
    # priority/position) по-прежнему игнорируют null.


class TaskMoveRequest(BaseModel):
    """Тело `POST /tasks/{id}/move`.

    Отдельная схема, а не поле в `TaskUpdate`: на том `extra="forbid"`, и
    вчерашний PWA-бандл получил бы 422 вместо no-op; плюс `update_task`
    расширяет права до viewer'а для `ASSIGNEE_EDITABLE_FIELDS`, а переносу
    там не место.
    """

    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    # Колонка в ЦЕЛЕВОМ проекте. `None` — «без статуса» (0046): задача есть в
    # списке и поиске, но не на доске. Колонки подзадач сервер подбирает по
    # имени сам.
    stage_id: UUID | None = None


class TaskMoveReport(BaseModel):
    """Что случится (`move-preview`) или что случилось (`move`).

    Один силуэт на оба ответа: предпросмотр и перенос считаются одним кодом
    (`services/task_move.py`), и разные формы ответа развели бы тексты в
    диалоге и в тосте.
    """

    project_id: UUID
    project_name: str
    # Новый «KEY-42». `None` у предпросмотра: номер выдаёт только сам перенос
    # (`allocate_task_seq`), а показывать несуществующий номер нельзя.
    new_key: str | None = None
    subtasks: int
    labels_kept: int
    labels_total: int
    values_kept: int
    values_total: int
    watchers_dropped: int
    dependencies_dropped: int
    shares_revoked: int
    # У цели активна публичная ссылка scope=project — задача станет видна по
    # ней анонимам (api/public.py::_build_project_view берёт ВСЕ задачи).
    target_public: bool


class TaskAssigneeAdd(BaseModel):
    """Тело POST /tasks/{id}/assignees — добавить одного исполнителя."""

    employee_id: UUID


class TaskRecurrenceBody(BaseModel):
    """Тело PUT /tasks/{id}/recurrence — идемпотентный upsert правила.

    Отдельная схема, а не поле в `TaskUpdate`: на том стоит `extra="forbid"`,
    и он же расширяет права до исполнителя-viewer для `done`/`stage_id`.
    Расписание — планирование, ему там не место.
    """

    model_config = ConfigDict(extra="forbid")

    freq: Literal["day", "weekday", "week", "month"]
    # `step`, а не `interval`: INTERVAL — зарезервированное слово Postgres.
    step: int = Field(default=1, ge=1, le=365)


class TaskRecurrenceInfo(BaseModel):
    """Правило + СЧИТАННАЯ СЕРВЕРОМ следующая дата.

    `next_due` приходит с сервера намеренно: второй реализации календарной
    арифметики на клиенте нет (тот же принцип, что у переноса задачи).
    """

    freq: Literal["day", "weekday", "week", "month"]
    step: int
    anchor: date
    occurrence: int
    next_due: date
    text: str


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    parent_task_id: UUID | None
    title: str
    description: str | None
    # Состояние задачи. Колонка к нему отношения не имеет (0044).
    done: bool
    # Колонка доски; имя фронт берёт из GET /projects/{id}/stages (один запрос
    # на проект, кэш), не из JOIN'а. `None` — «без статуса»: задача есть
    # в списке и поиске, но не на доске (0046).
    stage_id: UUID | None
    priority: TaskPriority
    # Источник истины для UI. Уволенные (shadow_users.deleted_at) сюда не
    # попадают, поэтому легаси-поля ниже с ним всегда согласованы — раньше
    # assignee_id мог быть непустым при assignee=null.
    assignees: list[AssigneeBrief] = []
    # DEPRECATED-выход: всегда выводится из assignees[0], а НЕ из ORM-атрибута —
    # поэтому удаление колонки в 0035 не потребует правок сериализации. Дефолт
    # None обязателен: без него model_validate(task) упадёт после 0035.
    assignee_id: UUID | None = None
    assignee: AssigneeBrief | None = None
    created_by: UUID
    start_at: datetime | None = None
    due_at: datetime | None
    # `false` — календарный день (мгновение условное, полдень display tz),
    # `true` — точный момент (0061).
    start_has_time: bool = False
    due_has_time: bool = False
    position: Decimal
    # Номер в проекте («KEY-42» = project.key + seq). project_key заполняют
    # только кросс-проектные ручки (/me/tasks) — в контексте проекта фронт
    # берёт key из project-запроса.
    seq: int
    project_key: str | None = None
    # Имя колонки доски. Заполняют только кросс-проектные ручки (/me/tasks):
    # в контексте проекта фронт берёт имена из GET /projects/{id}/stages, а на
    # «Моих задачах» колонки чужих проектов взять неоткуда.
    stage_name: str | None = None
    # «Задача лежит в чьём-то личном пространстве». Заполняют те же
    # кросс-проектные ручки. Чьём именно — НЕ говорим: `personal_owner_id`
    # наружу не отдаётся никогда, клиенту нужен только факт, чтобы подписать
    # строку «Личное» / «Личное коллеги» вместо имени проекта, которого он не
    # знает. Выводить это на клиенте из «проекта нет в GET /projects» нельзя:
    # так же выглядит обычный проект, из которого человека убрали.
    project_is_personal: bool | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    archived_at: datetime | None
    # Счётчики строки контекста в списке. Заполняет ТОЛЬКО list_tasks (батчем,
    # см. services/task_counts.py); одиночные ручки отдают None — «не знаем».
    # Клиент обязан различать None (чип не рисуем) и 0 (знаем, что нет), иначе
    # чип мигал бы при каждом оптимистичном обновлении.
    comment_count: int | None = None
    attachment_count: int | None = None
    blocker_count: int | None = None
    # Правило повтора. Заполняют батчем list_tasks, get_task, /me/tasks и обе
    # ручки повтора (services/task_recurrence.load_rules); остальные — None.
    recurrence: TaskRecurrenceInfo | None = None
    # Задача РОДИЛАСЬ по повтору вот этой. Обычная колонка — приезжает везде.
    recurrence_parent_id: UUID | None = None
    # Может ли ВЫЗЫВАЮЩИЙ закрывать задачу и двигать её по доске: роль owner/editor,
    # hub-admin ИЛИ он среди исполнителей (см. update_task). Заполняют только
    # list_tasks и get_task — там уже посчитана роль в проекте; остальные
    # ручки отдают None = «не знаем», клиент падает на can_edit проекта.
    #
    # ИНВАРИАНТ: ответ PATCH /tasks/{id} поле НЕ несёт и нести не должен —
    # useUpdateTask кладёт в кэш свой патч, а не ответ (web/src/hooks/useTasks.ts);
    # ответ с None затёр бы флаг и погасил контрол сразу после успешного клика.
    can_complete: bool | None = None
    # Задача шаблона проекта (0060): клиент гасит просрочку и галочку.
    is_template: bool = False


def resolve_assignee_ids(body: TaskCreate | TaskUpdate) -> list[UUID] | None:
    """Свести новый и легаси-вход к одному списку.

    Возврат: None — «исполнителей не трогать»; [] — «снять всех».

    `assignee_ids` побеждает при конфликте: прислать оба поля может только
    НОВЫЙ бандл, и делает он это ровно ради совместимости со старым бэкендом;
    жёсткая 422 сломала бы сценарий «новый фронт + откаченный бэк».
    """
    if "assignee_ids" in body.model_fields_set:
        return dedupe(body.assignee_ids or [])
    if "assignee_id" in body.model_fields_set:
        return [body.assignee_id] if body.assignee_id else []
    return None


class TaskImportReport(BaseModel):
    """Отчёт импорта задач из CSV (тот же силуэт, что у импорта сотрудников)."""

    created: int
    skipped: int
    errors: list[str]
    dry_run: bool

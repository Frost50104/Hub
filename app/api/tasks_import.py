"""Импорт задач из CSV (редизайн, волна 2): `POST /projects/{id}/tasks/import`.

Паттерн — импорт сотрудников (`employees.py`): UploadFile ≤2 МБ, utf-8-sig →
cp1251, разделитель по первой строке, построчные ошибки «Строка N: …»,
`dry_run` = вся работа + rollback. Задачи создаются через
`services/tasks.py::create_task_record` — общий путь с ручкой (seq через
`allocate_task_seq`, auto-watcher, исполнители), но БЕЗ её rate-limit
`task:write` 120/мин, который убил бы импорт на 121-й строке. У импорта свой
bucket `task:import` (5/мин). Row-lock проекта (seq) держится всю транзакцию —
допустимо: операция редкая, ≤2000 строк.

Колонки фиксированного шаблона (заголовок — как в таблице ниже, регистр не
важен): title* · description · assignee_email · due (ДД.ММ.ГГГГ или ISO) ·
priority (low|medium|high|urgent или низкий|средний|высокий|срочно) ·
section (алиас на метку) · stage (имя существующего этапа) ·
labels (имена существующих меток через «|»). Неизвестный исполнитель/этап/
метка — предупреждение в отчёте, задача создаётся без них: импорт не плодит
структуру проекта и не назначает «похожего» человека.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, date, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from signaris_auth import Principal
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import enforce_rate_limit, get_db_template_page, require_auth
from app.models.shadow import ShadowUser
from app.models.stage import ProjectStage
from app.models.task import TaskLabel, TaskLabelAssignment
from app.schemas.task import TaskCreate, TaskImportReport
from app.services.project_access import require_project_role
from app.services.taskdates import due_noon_utc
from app.services.tasks import create_task_record

router = APIRouter(tags=["tasks"])

_MAX_BYTES = 2 * 1024 * 1024
_MAX_ROWS = 2000
_COLUMNS = frozenset(
    {"title", "description", "assignee_email", "due", "priority", "section", "stage", "labels"}
)
_PRIORITY = {
    "low": "low",
    "medium": "medium",
    "high": "high",
    "urgent": "urgent",
    "низкий": "low",
    "средний": "medium",
    "обычный": "medium",
    "высокий": "high",
    "срочно": "urgent",
    "срочный": "urgent",
}


def _parse_due(raw: str) -> datetime | None:
    """«14.08.2026», «2026-08-14», «2026-08-14T10:00» → полдень display tz
    (`taskdates.due_noon_utc` — та же конвенция, что карточка и ассистент)."""
    raw = raw.strip()
    if not raw:
        return None
    for fmt in ("%d.%m.%Y", "%d.%m.%y"):
        try:
            d = datetime.strptime(raw, fmt).date()
            return due_noon_utc(d)
        except ValueError:
            pass
    try:
        if len(raw) == 10:
            d = date.fromisoformat(raw)
            return due_noon_utc(d)
        dt = datetime.fromisoformat(raw)
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except ValueError:
        return None


@router.post("/projects/{project_id}/tasks/import", response_model=TaskImportReport)
async def import_tasks(
    project_id: UUID,
    file: UploadFile = File(...),
    dry_run: bool = Query(default=False),
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db_template_page),
) -> TaskImportReport:
    await enforce_rate_limit(
        bucket="task:import", employee_id=str(principal.employee_id), limit=5, window_sec=60
    )
    await require_project_role(db, project_id, principal, allow=("owner", "editor"))

    raw = await file.read()
    if len(raw) > _MAX_BYTES:
        raise HTTPException(status_code=413, detail="CSV больше 2 МБ")
    try:
        text_data = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text_data = raw.decode("cp1251")
    lines = text_data.splitlines()
    first_line = lines[0] if lines else ""
    delimiter = ";" if first_line.count(";") >= first_line.count(",") else ","
    reader = csv.DictReader(io.StringIO(text_data), delimiter=delimiter)
    fields = [(f or "").strip().lower() for f in (reader.fieldnames or [])]
    if "title" not in fields:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="CSV должен содержать колонку title (разделитель ; или ,)",
        )

    # Справочники проекта — один раз, по имени (lower).
    stages = {
        s.name.strip().lower(): s
        for s in (
            await db.execute(
                select(ProjectStage).where(ProjectStage.project_id == project_id)
            )
        ).scalars()
    }
    labels = {
        label.name.strip().lower(): label
        for label in (
            await db.execute(select(TaskLabel).where(TaskLabel.project_id == project_id))
        ).scalars()
    }
    # Исполнители — только по email среди живых сотрудников тенанта: ФИО в
    # тенанте дублируются, а «похожий» человек хуже пустого поля.
    people = {
        (email or "").lower(): emp_id
        for emp_id, email in (
            await db.execute(
                select(ShadowUser.employee_id, ShadowUser.email).where(
                    ShadowUser.tenant_id == principal.tenant_id,
                    ShadowUser.deleted_at.is_(None),
                )
            )
        ).all()
    }

    created = 0
    skipped = 0
    errors: list[str] = []
    warned_unknown = False
    for line_no, row in enumerate(reader, start=2):
        if created + skipped >= _MAX_ROWS:
            errors.append(
                f"Строка {line_no}: лимит {_MAX_ROWS} строк за один импорт — остальное не прочитано"
            )
            break
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        unknown = set(row) - _COLUMNS - {""}
        if unknown and not warned_unknown:
            warned_unknown = True
            errors.append(f"Неизвестные колонки игнорируются: {', '.join(sorted(unknown))}")
        title = row.get("title", "")
        if not title:
            errors.append(f"Строка {line_no}: пустой title — пропущена")
            skipped += 1
            continue

        priority = "medium"
        if row.get("priority"):
            mapped = _PRIORITY.get(row["priority"].lower())
            if mapped is None:
                errors.append(
                    f"Строка {line_no}: приоритет «{row['priority']}» не распознан — "
                    "поставлен средний"
                )
            else:
                priority = mapped

        due = None
        if row.get("due"):
            due = _parse_due(row["due"])
            if due is None:
                errors.append(
                    f"Строка {line_no}: срок «{row['due']}» не распознан "
                    "(нужен ДД.ММ.ГГГГ или ГГГГ-ММ-ДД) — без срока"
                )

        stage = stages.get(row.get("stage", "").lower()) if row.get("stage") else None
        if row.get("stage") and stage is None:
            # Куда попадёт задача, зависит от того, есть ли у проекта колонки
            # вообще: обещать «первый этап» проекту без колонок — враньё.
            fallback = "в первую колонку" if stages else "без колонки"
            errors.append(
                f"Строка {line_no}: колонка «{row['stage']}» не найдена — {fallback}"
            )

        assignee_ids: list[UUID] = []
        if row.get("assignee_email"):
            emp = people.get(row["assignee_email"].lower())
            if emp is None:
                errors.append(
                    f"Строка {line_no}: исполнитель {row['assignee_email']} не найден — "
                    "без исполнителя"
                )
            else:
                assignee_ids = [emp]

        # `section` — алиас на метку. Секций больше нет, но у людей остались
        # заготовленные файлы с этой колонкой, а имена совпадают один в один:
        # переезд секций в метки сохранил их дословно. Молча ронять колонку
        # значило бы потерять разбивку без единого слова в отчёте.
        label_names = [x.strip() for x in (row.get("labels") or "").split("|") if x.strip()]
        if row.get("section"):
            label_names.append(row["section"].strip())

        label_ids: list[UUID] = []
        for name in label_names:
            label = labels.get(name.lower())
            if label is None:
                errors.append(f"Строка {line_no}: метка «{name}» не найдена — пропущена")
            else:
                label_ids.append(label.id)

        body = TaskCreate(
            title=title[:500],
            description=(row.get("description") or None),
            stage_id=stage.id if stage else None,
            priority=priority,  # type: ignore[arg-type]
            assignee_ids=assignee_ids or None,
            due_at=due,
        )
        task = await create_task_record(db, principal=principal, project_id=project_id, body=body)
        if label_ids:
            await db.execute(
                pg_insert(TaskLabelAssignment)
                .values(
                    [
                        {"task_id": task.id, "label_id": lid, "tenant_id": principal.tenant_id}
                        for lid in label_ids
                    ]
                )
                .on_conflict_do_nothing()
            )
        created += 1

    if dry_run:
        await db.rollback()
        return TaskImportReport(created=created, skipped=skipped, errors=errors, dry_run=True)
    await db.commit()
    return TaskImportReport(created=created, skipped=skipped, errors=errors, dry_run=False)


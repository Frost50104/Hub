"""Кэш WEEEK → `weeek-bundle/`, который джоба на VPS просто записывает.

    python -m tools.import_weeek.build_bundle --out weeek-bundle

Bundle самодостаточен: ни сети, ни токена на сервере. Всё, что требует
решения — порядок задач, номера, слияние колонок, конвертация описаний,
разбор подзадач — посчитано ЗДЕСЬ и детерминировано: повторная сборка на том
же кэше даёт тот же результат, иначе повторный импорт переставил бы карточки.

Чего bundle НЕ решает (это знает только джоба, у неё есть база):
ключ проекта при коллизии, резолв email в employee_id, id строк в Hub.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

from app.models.custom_field import CustomFieldDefinition
from app.services.custom_field_validator import CustomFieldValueError, validate
from tools.import_weeek.html_to_md import html_to_md
from tools.import_weeek.mapping import (
    day_of,
    key_hint,
    merge_sections,
    merge_stages,
    priority_of,
    resolve_parents,
    root_portfolio,
    select_projects,
    select_tasks,
    task_sort_key,
)
from tools.import_weeek.weeek_api import DEFAULT_CACHE, WeeekClient

MANIFEST_VERSION = 1

# Расширение → MIME. Только то, что пройдёт `ALLOWED_MIME` в Hub: белый список
# вложений — защитный инвариант с зеркалом на фронте, и расширять его ради
# переноса нельзя. Остальное уедет в описание именем файла.
EXT_MIME: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".heic": "image/heic",
    ".heif": "image/heif",
    ".pdf": "application/pdf",
    ".zip": "application/zip",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".csv": "text/csv",
    ".json": "application/json",
}

# WEEEK → Hub. `member` намеренно уезжает в `text` с ФИО, а не в `person`:
# `person` требует employee_id, а он есть у пяти человек из 41 — 96% значений
# просто пропали бы.
CF_TYPE: dict[str, str] = {
    "text": "text",
    "select": "select",
    "boolean": "checkbox",
    "member": "text",
    "number": "number",
    "date": "date",
}

_IMG_SRC = re.compile(r'<img[^>]+src="([^"]+)"')


@dataclass
class Report:
    counters: Counter = field(default_factory=Counter)
    notes: list[str] = field(default_factory=list)

    def bump(self, key: str, delta: int = 1) -> None:
        self.counters[key] += delta

    def note(self, text: str) -> None:
        self.notes.append(text)


def _people(members: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for m in members:
        name = " ".join(x for x in (m.get("lastName"), m.get("firstName")) if x).strip()
        out[str(m["id"])] = {
            "email": (m.get("email") or "").strip().lower(),
            "name": name or (m.get("email") or ""),
        }
    return out


def _inline_image_ids(description: str | None) -> set[str]:
    """id файлов, на которые ссылается `<img>` в описании.

    Сами эти URL уже не скачиваются (403, подписи в них нет), но 98 из 101
    картинки лежат ещё и во `attachments[]` задачи — оттуда ссылка живая.
    Такие картинки тянем даже у выполненных задач: без файла текст вокруг
    «Изображение: …» теряет смысл.
    """
    out: set[str] = set()
    for src in _IMG_SRC.findall(description or ""):
        out.add(src.rstrip("/").split("/")[-1].split("?")[0])
    return out


# id опции у Hub — `max_length=32` (`app/schemas/custom_field.py:24`), а WEEEK
# отдаёт 36-символьный UUID с дефисами. Схема ответа отвергает такое значение
# уже ПОСЛЕ записи (в JSONB ограничения нет), и ручка списка полей отдаёт 500 —
# поймано репетицией на staging 25.08. `.hex` даёт ровно 32 символа и остаётся
# детерминированным.
def _option_id(raw: object) -> str:
    text = str(raw)
    try:
        return UUID(text).hex
    except ValueError:
        return text[:32]


def _is_blank(value: object) -> bool:
    """Пустое значение кастом-поля WEEEK.

    `False` считается пустым намеренно: снятая галочка неотличима от «поле не
    трогали», это дефолт. Без этого «Компенсация» (одно поле бухгалтерии)
    завела бы определение в каждом из 47 проектов и значение у каждой из
    16 703 задач.
    """
    return value is None or value is False or value == "" or value == []


def _custom_field_specs(tasks: list[dict], report: Report) -> list[dict]:
    """Определения кастом-полей проекта — только те, где есть хоть одно значение.

    Иначе 47 проектов обросли бы шестью пустыми колонками каждый.
    """
    used: dict[str, dict] = {}
    for task in tasks:
        for raw in task.get("customFields") or []:
            value = raw.get("value")
            if _is_blank(value):
                continue
            name = (raw.get("name") or "").strip()
            if not name:
                # У WEEEK есть безымянные определения с единичными значениями —
                # в Hub у поля имя обязательно, переносить нечего.
                report.bump("кастом-поле без имени пропущено")
                continue
            hub_type = CF_TYPE.get(raw.get("type") or "")
            if hub_type is None:
                report.note(f"кастом-поле «{name}»: тип {raw.get('type')} не поддержан")
                continue
            spec = used.setdefault(
                str(raw["id"]),
                {
                    "weeek_id": str(raw["id"]),
                    "name": name[:64],
                    "type": hub_type,
                    "options": [],
                    "position": len(used) + 1,
                },
            )
            if hub_type == "select" and not spec["options"]:
                spec["options"] = [
                    {"id": _option_id(o["id"]), "label": (o.get("name") or "")[:64],
                     "color": o.get("color") or None}
                    for o in raw.get("options") or []
                ]
    return list(used.values())


def _custom_values(
    task: dict, specs: dict[str, dict], people: dict[str, dict], report: Report
) -> list[dict]:
    out: list[dict] = []
    for raw in task.get("customFields") or []:
        spec = specs.get(str(raw.get("id")))
        value = raw.get("value")
        if spec is None or _is_blank(value):
            continue
        if raw.get("type") == "member":
            names = [people.get(str(u), {}).get("name") or str(u) for u in value]
            value = ", ".join(n for n in names if n)[:2000]
        elif spec["type"] == "select":
            value = _option_id(value)
        elif spec["type"] == "multi_select":
            value = [_option_id(v) for v in value]
        elif spec["type"] == "text" and not isinstance(value, str):
            value = str(value)[:2000]
        # Валидируем ЗДЕСЬ: на проде 422 внутри пачки уронил бы весь чанк.
        probe = CustomFieldDefinition(
            name=spec["name"], type=spec["type"], options=spec["options"]
        )
        try:
            value = validate(probe, value)
        except CustomFieldValueError as exc:
            report.note(f"задача {task['id']}, поле «{spec['name']}»: {exc}")
            continue
        out.append({"field": spec["weeek_id"], "value": value})
    return out



# Магические байты: расширение врёт чаще, чем кажется. В выгрузке нашлись
# «IMG_7866.HEIC», который на самом деле JPEG, «Season menu.png» — WebP и
# «…jpg» — PNG. Hub такие файлы отвергает (`sniff_mismatch`), поэтому MIME
# определяем ПО СОДЕРЖИМОМУ, а расширение оставляем для семейств без
# однозначной сигнатуры (zip/OLE/текст).
_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)


def _sniff_mime(head: bytes, ext_mime: str) -> str:
    """MIME по первым байтам; расширение — фолбэк."""
    for magic, mime in _SIGNATURES:
        if head.startswith(magic):
            return mime
    if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return "image/webp"
    if head[4:8] == b"ftyp":
        # HEIC/HEIF: конкретный бренд не различаем, доверяем расширению,
        # если оно из этого же семейства.
        return ext_mime if ext_mime.startswith(("image/heic", "image/heif")) else "image/heic"
    if b"%PDF" in head[:1024]:
        return "application/pdf"
    return ext_mime


def _attachment_row(att: dict, cached: Path, people: dict[str, dict]) -> dict:
    # Автора файла резолвим ЗДЕСЬ: `task_attachments.uploaded_by` — FK RESTRICT
    # на shadow_users, и джобе нужен email, а не внутренний id WEEEK.
    creator = people.get(str(att.get("creatorId") or ""), {})
    ext_mime = EXT_MIME[Path(att.get("name") or "").suffix.lower()]
    with cached.open("rb") as fh:
        head = fh.read(1024)
    return {
        "weeek_id": str(att["id"]),
        "file": f"files/{att['id']}",
        "name": (att.get("name") or "file")[:255],
        "mime": _sniff_mime(head, ext_mime),
        "size": cached.stat().st_size,
        "creator_email": creator.get("email") or None,
    }


def build_project(
    project: dict,
    tasks: list[dict],
    *,
    api: WeeekClient,
    people: dict[str, dict],
    parents: dict[int, Any],
    by_id: dict[int, dict],
    folder_key: str | None,
    files_dir: Path,
    skip_files: bool,
    report: Report,
) -> tuple[dict, list[dict]]:
    pid = int(project["id"])
    boards = [
        {**b, "columns": api.board_columns(int(b["id"]))} for b in api.boards(pid)
    ]
    stages, stage_by_column = merge_stages(boards)
    sections = merge_sections(boards)
    section_ids = {s.board_id for s in sections}

    ordered = sorted(tasks, key=task_sort_key)

    cf_specs = _custom_field_specs(ordered, report)
    cf_by_id = {s["weeek_id"]: s for s in cf_specs}

    position_of: Counter = Counter()
    rows: list[dict] = []
    for seq, task in enumerate(ordered, start=1):
        tid = int(task["id"])
        column_id = task.get("boardColumnId")
        # Колонки нет или её удалили в WEEEK → задача приезжает БЕЗ статуса
        # (0046): она есть в списке и поиске, но не на доске.
        stage_key = stage_by_column.get(int(column_id)) if column_id else None
        if stage_key is None:
            report.bump("задач без статуса")
        position_of[stage_key] += 1

        inline_ids = _inline_image_ids(task.get("description"))
        attachments, names_only, images = _collect_files(
            task, api=api, files_dir=files_dir, inline_ids=inline_ids,
            skip_files=skip_files, people=people, report=report,
        )
        body, notes = html_to_md(task.get("description"), images=images)
        for n in notes:
            report.bump(n.split(":")[0])

        decision = parents[tid]
        parent_ref = None
        if decision.note_kind:
            ref = by_id.get(decision.note_ref or -1) or {}
            parent_ref = {
                "kind": decision.note_kind,
                "weeek_id": decision.note_ref,
                "title": (ref.get("title") or "")[:200],
                "project_weeek_id": ref.get("projectId"),
            }
            report.bump(f"подзадач: {decision.note_kind}")

        author = people.get(str(task.get("authorId") or ""), {})
        assignees = [
            {"email": people[str(a)]["email"], "name": people[str(a)]["name"]}
            for a in (task.get("assignees") or [])
            if str(a) in people and people[str(a)]["email"]
        ]
        rows.append(
            {
                "weeek_id": tid,
                "seq": seq,
                "position": position_of[stage_key],
                "title": (task.get("title") or "").strip()[:500] or "Без названия",
                "body_md": body,
                "priority": priority_of(task.get("priority")),
                "done": bool(task.get("isCompleted")),
                "created_at": task.get("createdAt"),
                "updated_at": task.get("updatedAt"),
                "completed_at": task.get("completedAt")
                or (task.get("updatedAt") if task.get("isCompleted") else None),
                "due_day": _iso(day_of(task.get("dueDate"), task.get("dueDateTime"))),
                "start_day": _iso(day_of(task.get("startDate"), task.get("startDateTime"))),
                "stage_key": stage_key,
                "section_board_id": (
                    int(task["boardId"])
                    if task.get("boardId") and int(task["boardId"]) in section_ids
                    else None
                ),
                "parent_weeek_id": decision.parent_weeek_id,
                "parent_ref": parent_ref,
                "author_email": author.get("email") or None,
                "assignees": assignees,
                "custom_values": _custom_values(task, cf_by_id, people, report),
                "attachments": attachments,
                "attachment_names_only": names_only,
            }
        )
        report.bump("задач")

    spec = {
        "weeek_id": pid,
        "name": (project.get("title") or project.get("name") or "Проект")[:255],
        "key_hint": key_hint(project.get("title") or project.get("name") or ""),
        "description": (project.get("description") or "").strip()[:4000] or None,
        "folder_key": folder_key,
        "tasks_file": f"projects/{pid}.json",
        "task_count": len(rows),
        "max_seq": len(rows),
        "stages": [{"key": s.key, "name": s.name, "position": s.position} for s in stages],
        "sections": [
            {"weeek_board_id": s.board_id, "name": s.name, "position": s.position}
            for s in sections
        ],
        "custom_fields": cf_specs,
        "team_emails": sorted(
            {people[str(u)]["email"] for u in (project.get("team") or [])
             if str(u) in people and people[str(u)]["email"]}
        ),
    }
    return spec, rows


def _collect_files(
    task: dict,
    *,
    api: WeeekClient,
    files_dir: Path,
    inline_ids: set[str],
    skip_files: bool,
    people: dict[str, dict],
    report: Report,
) -> tuple[list[dict], list[str], dict[str, str]]:
    """→ (вложения для Hub, имена «только в описание», карта src → имя файла).

    Решение владельца: файлы тянем у ОТКРЫТЫХ задач. Исключение — картинки,
    на которые ссылается описание: без них текст вокруг «Изображение: …»
    бессмысленный, а таких всего сотня на весь перенос.
    """
    detail = api.task_detail(int(task["id"]))
    raw = detail.get("attachments") or []
    if not raw:
        return [], [], {}
    is_open = not task.get("isCompleted")
    attachments: list[dict] = []
    names_only: list[str] = []
    images: dict[str, str] = {}
    for att in raw:
        name = att.get("name") or "file"
        att_id = str(att["id"])
        wanted = is_open or att_id in inline_ids
        ext = Path(name).suffix.lower()
        if not wanted:
            names_only.append(name)
            continue
        if ext not in EXT_MIME:
            names_only.append(name)
            report.bump(f"вне белого списка: {ext or 'без расширения'}")
            continue
        if skip_files:
            names_only.append(name)
            continue
        cached = api.download(att.get("url") or "", att_id)
        if cached is None:
            names_only.append(name)
            report.bump("файл не скачался")
            continue
        target = files_dir / att_id
        if not target.exists():
            shutil.copyfile(cached, target)
        row = _attachment_row(att, cached, people)
        if row["mime"] != EXT_MIME[ext]:
            report.bump(f"MIME по содержимому: {ext} → {row['mime']}")
        attachments.append(row)
        report.bump("файлов перенесено")
        report.bump("байт файлов", cached.stat().st_size)
        if att_id in inline_ids:
            for src in _IMG_SRC.findall(task.get("description") or ""):
                if src.rstrip("/").split("/")[-1].split("?")[0] == att_id:
                    images[src] = name
    return attachments, names_only, images


def _iso(value) -> str | None:  # noqa: ANN001
    return value.isoformat() if value is not None else None


def main() -> int:  # noqa: C901 — линейный сценарий сборки, дробить нечего
    parser = argparse.ArgumentParser(description="Собрать bundle для импорта в Hub")
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--out", type=Path, default=Path("weeek-bundle"))
    parser.add_argument("--skip-files", action="store_true", help="без скачивания вложений")
    args = parser.parse_args()

    out: Path = args.out
    (out / "projects").mkdir(parents=True, exist_ok=True)
    (out / "files").mkdir(parents=True, exist_ok=True)
    report = Report()

    with WeeekClient(cache=args.cache) as api:
        projects = api.projects()
        portfolios = {int(p["id"]): p for p in api.portfolios()}
        members = api.members()
        all_tasks = api.all_tasks()

        people = _people(members)
        scope_ids = select_projects(projects, all_tasks)
        scope_tasks = select_tasks(all_tasks, scope_ids)
        by_id = {int(t["id"]): t for t in all_tasks}
        parents = resolve_parents(by_id, {int(t["id"]) for t in scope_tasks})

        by_project: dict[int, list[dict]] = defaultdict(list)
        for task in scope_tasks:
            by_project[int(task["projectId"])].append(task)

        folders: dict[str, dict] = {}
        project_specs: list[dict] = []
        for project in sorted(projects, key=lambda p: int(p["id"])):
            pid = int(project["id"])
            if pid not in scope_ids:
                continue
            root = root_portfolio(portfolios, project.get("portfolioId"))
            folder_key = None
            if root:
                folder_key = str(root["id"])
                folders.setdefault(
                    folder_key,
                    {"weeek_id": folder_key, "name": (root.get("name") or "")[:255],
                     "position": len(folders)},
                )
            spec, rows = build_project(
                project, by_project[pid], api=api, people=people, parents=parents,
                by_id=by_id, folder_key=folder_key, files_dir=out / "files",
                skip_files=args.skip_files, report=report,
            )
            project_specs.append(spec)
            (out / spec["tasks_file"]).write_text(
                json.dumps({"weeek_project_id": pid, "tasks": rows}, ensure_ascii=False),
                encoding="utf-8",
            )
            report.bump("проектов")
            print(f"  [{pid}] {spec['key_hint']:<10} {spec['task_count']:>5} задач  "
                  f"{spec['name'][:44]}")

    stats = {
        "projects": len(project_specs),
        "tasks": sum(p["task_count"] for p in project_specs),
        "open": sum(1 for t in scope_tasks if not t.get("isCompleted")),
        "done": sum(1 for t in scope_tasks if t.get("isCompleted")),
        "subtasks": sum(1 for t in scope_tasks if t.get("parentId")),
        "folders": len(folders),
        "attachments": report.counters["файлов перенесено"],
        "attachment_bytes": report.counters["байт файлов"],
    }
    manifest = {
        "version": MANIFEST_VERSION,
        "source": "weeek",
        "stats": stats,
        "folders": list(folders.values()),
        "projects": project_specs,
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    (out / "people.json").write_text(
        json.dumps({"members": list(people.values())}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    _write_report(out, stats, report)
    print("\n" + "\n".join(f"  {k}: {v}" for k, v in stats.items()))
    print(f"\nбандл: {out}")
    return 0


def _write_report(out: Path, stats: dict, report: Report) -> None:
    lines = ["# Сборка bundle WEEEK → Hub", "", "## Числа", ""]
    lines += [f"- {k}: {v}" for k, v in stats.items()]
    lines += ["", "## Счётчики", ""]
    lines += [f"- {k}: {v}" for k, v in sorted(report.counters.items())]
    if report.notes:
        lines += ["", "## Замечания", ""]
        lines += [f"- {n}" for n in report.notes[:500]]
        if len(report.notes) > 500:
            lines.append(f"- … ещё {len(report.notes) - 500}")
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out / "report.json").write_text(
        json.dumps({"stats": stats, "counters": dict(report.counters),
                    "notes": report.notes}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )


if __name__ == "__main__":
    sys.exit(main())

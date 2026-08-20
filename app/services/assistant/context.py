"""Контекст инструментов ассистента и резолверы «человеческое → id».

Модель оперирует тем, что сказал сотрудник: «UppetitTV», «Дмитрию»,
«задача 133», «UPPETITTV-207». Инструментам нужны UUID. Разбор живёт здесь,
а не в каждом инструменте, и подчиняется двум правилам:

- **Видимость считается теми же гейтами, что и в API.** Никаких «поищем по
  всему тенанту, а права проверим потом»: невидимый проект не должен даже
  появляться в списке кандидатов, иначе ассистент подтвердит его
  существование отказом.
- **Неоднозначность — не ошибка.** Резолвер возвращает список кандидатов,
  модель переспрашивает. Молча выбрать первого Дмитрия из трёх — худший из
  возможных исходов, потому что задача уедет не тому.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import UUID

from signaris_auth import Principal
from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employee_profile import EmployeeProfile
from app.models.project import Project, ProjectMember
from app.models.shadow import ShadowUser
from app.models.task import Task
from app.services.project_access import is_hub_admin

_TASK_KEY_RE = re.compile(r"^\s*([A-Za-zА-Яа-я0-9]{1,16})[-\s]?(\d{1,7})\s*$")
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


@dataclass
class ToolContext:
    """Всё, что нужно инструменту: сессия, кто спрашивает, учебный профиль."""

    db: AsyncSession
    principal: Principal
    # None — у сотрудника нет учебного профиля: база знаний недоступна,
    # трекер работает.
    profile: EmployeeProfile | None

    @property
    def employee_id(self) -> UUID:
        return self.principal.employee_id

    @property
    def tenant_id(self) -> UUID:
        return self.principal.tenant_id

    @property
    def is_admin(self) -> bool:
        return is_hub_admin(self.principal)


class Ambiguous(Exception):
    """Совпало несколько объектов — модель обязана переспросить."""

    def __init__(self, what: str, candidates: list[str]) -> None:
        self.what = what
        self.candidates = candidates
        super().__init__(f"{what}: {', '.join(candidates)}")


class NotFound(Exception):
    """Ничего не совпало — или нет, или невидимо (различать нельзя)."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


def visible_projects_stmt(ctx: ToolContext) -> Select[tuple[Project]]:
    """Проекты, которые сотрудник ВПРАВЕ видеть. RLS отсекает чужой тенант,
    членство — чужие проекты; hub-admin видит весь тенант (как в API)."""
    stmt = select(Project)
    if not ctx.is_admin:
        stmt = stmt.join(ProjectMember, ProjectMember.project_id == Project.id).where(
            ProjectMember.employee_id == ctx.employee_id
        )
    return stmt


async def resolve_project(ctx: ToolContext, ref: str) -> Project:
    """«UppetitTV» / «UPTV» / UUID → проект. Точное совпадение ключа или
    имени бьёт частичное: иначе «Отдел» выбрал бы «Отдел персонала» при
    наличии проекта ровно с именем «Отдел»."""
    ref = (ref or "").strip()
    if not ref:
        raise NotFound("Не указан проект")
    base = visible_projects_stmt(ctx)

    if _UUID_RE.match(ref):
        found = (await ctx.db.execute(base.where(Project.id == UUID(ref)))).scalars().first()
        if found is None:
            raise NotFound(f"Проект {ref} не найден или недоступен")
        return found

    exact = (
        (
            await ctx.db.execute(
                base.where(
                    or_(
                        func.lower(Project.key) == ref.lower(),
                        func.lower(Project.name) == ref.lower(),
                    )
                )
            )
        )
        .scalars()
        .all()
    )
    if len(exact) == 1:
        return exact[0]

    rows = (
        (await ctx.db.execute(base.where(Project.name.ilike(f"%{ref}%")).limit(6)))
        .scalars()
        .all()
    )
    if not rows:
        raise NotFound(f"Проект «{ref}» не найден или у вас нет к нему доступа")
    if len(rows) > 1:
        raise Ambiguous(
            f"Под «{ref}» подходит несколько проектов",
            [f"{p.name} ({p.key})" for p in rows],
        )
    return rows[0]


async def resolve_person(ctx: ToolContext, ref: str) -> ShadowUser:
    """«Дмитрию» / «Дмитрий Фёдоров» / email → сотрудник тенанта.

    Уволенные (`deleted_at`) исключены — тот же фильтр, что во всех списках
    сотрудников: ассистент не должен назначать задачу человеку, которого
    больше нет.
    """
    ref = (ref or "").strip()
    if not ref:
        raise NotFound("Не указан сотрудник")
    base = select(ShadowUser).where(ShadowUser.deleted_at.is_(None))

    if _UUID_RE.match(ref):
        found = (
            await ctx.db.execute(base.where(ShadowUser.employee_id == UUID(ref)))
        ).scalars().first()
        if found is None:
            raise NotFound(f"Сотрудник {ref} не найден")
        return found

    exact = (
        (
            await ctx.db.execute(
                base.where(
                    or_(
                        func.lower(ShadowUser.full_name) == ref.lower(),
                        func.lower(ShadowUser.email) == ref.lower(),
                    )
                )
            )
        )
        .scalars()
        .all()
    )
    if len(exact) == 1:
        return exact[0]

    # «Дмитрию» → ищем и по началу слова: словоформа не совпадёт с ФИО
    # целиком, а вот «Дмитр» — общий префикс всех падежей.
    stem = ref[:-1] if len(ref) > 4 else ref
    rows = (
        (
            await ctx.db.execute(
                base.where(
                    or_(
                        ShadowUser.full_name.ilike(f"%{ref}%"),
                        ShadowUser.full_name.ilike(f"%{stem}%"),
                    )
                ).limit(6)
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        raise NotFound(f"Сотрудник «{ref}» не найден")
    if len(rows) > 1:
        raise Ambiguous(
            f"Под «{ref}» подходит несколько сотрудников",
            [u.full_name or u.email or str(u.employee_id) for u in rows],
        )
    return rows[0]


async def resolve_task(ctx: ToolContext, ref: str) -> Task:
    """«UPPETITTV-207» / UUID → задача из видимого проекта.

    Голый номер («задача 133») сознательно НЕ поддерживаем: `seq` уникален
    внутри проекта, и без ключа 133 — это до семи разных задач.
    """
    ref = (ref or "").strip()
    if not ref:
        raise NotFound("Не указана задача")
    projects = visible_projects_stmt(ctx).subquery()

    if _UUID_RE.match(ref):
        found = (
            await ctx.db.execute(
                select(Task)
                .join(projects, projects.c.id == Task.project_id)
                .where(Task.id == UUID(ref))
            )
        ).scalars().first()
        if found is None:
            raise NotFound(f"Задача {ref} не найдена или недоступна")
        return found

    m = _TASK_KEY_RE.match(ref)
    if not m:
        raise NotFound(
            f"«{ref}» не похоже на номер задачи — нужен вид «UPPETITTV-207»"
        )
    key, seq = m.group(1), int(m.group(2))
    found = (
        await ctx.db.execute(
            select(Task)
            .join(projects, projects.c.id == Task.project_id)
            .where(func.lower(projects.c.key) == key.lower(), Task.seq == seq)
        )
    ).scalars().first()
    if found is None:
        raise NotFound(f"Задача {ref.upper()} не найдена или у вас нет доступа")
    return found

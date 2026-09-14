"""Персональные настройки интерфейса (пока одна — тема оформления).

Живут в `user_preferences` по ключу `shadow_users.employee_id`: тема принадлежит
учётной записи, а не браузеру (см. докстроку модели). Сборка запроса отделена от
исполнения ради юнит-теста на компиляцию SQL: интеграционные тесты в CI не
бегут (`.github/workflows/ci.yml` гоняет `pytest -m "not integration"`).
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import Insert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_preference import UserPreference

Theme = Literal["light", "dark"]


def theme_stmt(employee_id: UUID):
    """SELECT темы. RLS сам ограничит тенантом — `WHERE tenant_id` не пишем."""
    return select(UserPreference.theme).where(
        UserPreference.employee_id == employee_id
    )


def upsert_theme_stmt(*, employee_id: UUID, tenant_id: UUID, theme: Theme) -> Insert:
    return (
        pg_insert(UserPreference)
        .values(
            employee_id=employee_id,
            tenant_id=tenant_id,
            theme=theme,
            updated_at=func.now(),
        )
        .on_conflict_do_update(
            index_elements=["employee_id"],
            set_={"theme": theme, "updated_at": func.now()},
        )
    )


async def get_theme(db: AsyncSession, employee_id: UUID) -> str | None:
    """Тема пользователя или None — «строки нет» и «тему не выбирали» для
    клиента одно и то же: он вправе засеять её локальным выбором."""
    return await db.scalar(theme_stmt(employee_id))


async def set_theme(
    db: AsyncSession, *, employee_id: UUID, tenant_id: UUID, theme: Theme
) -> None:
    await db.execute(
        upsert_theme_stmt(employee_id=employee_id, tenant_id=tenant_id, theme=theme)
    )
    await db.commit()

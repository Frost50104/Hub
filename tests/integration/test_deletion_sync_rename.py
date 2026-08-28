"""`employee_updated` из фида auth → имя в HR-карточке сотрудника.

До 28.08 имя в Hub обновлялось только запросами самого человека: пока он не
зайдёт, переименование в auth до продукта не доезжало. Auth завёл событие в
продуктовом фиде (lib ≥ 0.8.0), библиотека обновляет по нему `shadow_users`
сама, а вторую копию имени — `employee_profiles.full_name`, ту, что видно на
learn-экранах и в сертификатах, — пишет обработчик Hub.

Тестов у deletion-sync не было вовсе; здесь покрыта новая ветка и то, что
делает её безопасной: идемпотентность, отказ создавать карточки и молчание на
незнакомых событиях (исключение в `on_event` заморозило бы курсор, а с ним
весь фид, включая будущие удаления).
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from signaris_auth.shadow import upsert_shadow_tenant, upsert_shadow_user
from signaris_auth.sync import DeletionEvent
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.employee_profile import EmployeeProfile
from app.services.deletion_sync import _on_event
from app.services.employee_profiles import ensure_profile_for_principal
from tests.integration.conftest import make_principal

pytestmark = pytest.mark.integration


def _event(
    *,
    tenant_id: uuid.UUID,
    employee_id: uuid.UUID | None,
    full_name: str | None,
    event_type: str = "employee_updated",
    seq: int = 17,
) -> DeletionEvent:
    return DeletionEvent(
        seq=seq,
        event_type=event_type,
        employee_id=employee_id,
        tenant_id=tenant_id,
        created_at=dt.datetime.now(dt.UTC),
        full_name=full_name,
    )


async def _person(db: AsyncSession, tenant_id: uuid.UUID, slug: str, name: str):
    """Сотрудник, который однажды заходил: есть и зеркало, и HR-карточка."""
    principal = make_principal(
        tenant_id, email=f"{slug}@t.ru", full_name=name, tenant_slug=slug
    )
    await upsert_shadow_tenant(db, principal, table="shadow_tenants")
    await upsert_shadow_user(db, principal, table="shadow_users")
    result = await ensure_profile_for_principal(db, principal)
    await db.commit()
    assert result.profile is not None
    return principal, result.profile.id


async def _profile_name(db: AsyncSession, profile_id: uuid.UUID) -> str:
    # Обработчик пишет в СВОЕЙ сессии — снимок нашей нужно обновить.
    await db.commit()
    return (
        await db.execute(
            select(EmployeeProfile.full_name).where(EmployeeProfile.id == profile_id)
        )
    ).scalar_one()


async def _audit_rows(db: AsyncSession, profile_id: uuid.UUID):
    return (
        await db.execute(
            select(AuditLog.actor_id, AuditLog.diff).where(
                AuditLog.object_type == "employee_profile",
                AuditLog.object_id == profile_id,
            )
        )
    ).all()


async def test_rename_reaches_the_profile_and_the_journal(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Главный случай: человек в Hub не заходил, а имя всё равно доехало."""
    person, profile_id = await _person(db, tenant_id, "ren1", "Скробот Мария")

    await _on_event(
        db,
        _event(
            tenant_id=tenant_id,
            employee_id=person.employee_id,
            full_name="HR Пользователь",
        ),
    )

    assert await _profile_name(db, profile_id) == "HR Пользователь"

    rows = await _audit_rows(db, profile_id)
    renames = [r for r in rows if r.diff and "full_name" in r.diff]
    assert len(renames) == 1
    # Инициатор — auth, а не человек в Hub: actor_id обязан быть пустым.
    assert renames[0].actor_id is None
    assert renames[0].diff["full_name"]["new"] == "HR Пользователь"


async def test_repeat_of_the_same_event_changes_nothing(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Курсор двигается ПОСЛЕ обработчика — событие переигрывается штатно."""
    person, profile_id = await _person(db, tenant_id, "ren2", "Старое Имя")
    event = _event(
        tenant_id=tenant_id, employee_id=person.employee_id, full_name="Новое Имя"
    )

    await _on_event(db, event)
    await _on_event(db, event)

    assert await _profile_name(db, profile_id) == "Новое Имя"
    renames = [r for r in await _audit_rows(db, profile_id) if r.diff]
    assert len(renames) == 1, "повтор не должен плодить записи в журнале"


async def test_blank_name_does_not_wipe_the_card(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Имя — единственный опознавательный признак человека в списках."""
    person, profile_id = await _person(db, tenant_id, "ren3", "Ломов Александр")

    for empty in (None, "", "   "):
        await _on_event(
            db,
            _event(
                tenant_id=tenant_id, employee_id=person.employee_id, full_name=empty
            ),
        )

    assert await _profile_name(db, profile_id) == "Ломов Александр"
    assert await _audit_rows(db, profile_id) == []


async def test_unknown_employee_creates_nothing(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Фид не должен становиться каналом создания записей о людях.

    Карточки нет — значит человек в Hub не приходил и HR его не заводил; имя
    подтянется при первом входе (`_sync_linked_profile`).
    """
    before = (
        await db.execute(select(EmployeeProfile.id))
    ).scalars().all()

    await _on_event(
        db,
        _event(tenant_id=tenant_id, employee_id=uuid.uuid4(), full_name="Кто-то Новый"),
    )

    await db.commit()
    after = (await db.execute(select(EmployeeProfile.id))).scalars().all()
    assert sorted(map(str, after)) == sorted(map(str, before))


async def test_incomplete_and_unknown_events_do_not_raise(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Исключение здесь заморозило бы курсор, а с ним весь фид.

    Незнакомый тип события — не гипотеза: ровно так прод прожевал бэкфилл
    `employee_updated` на старой библиотеке, ничего не применив и не упав.
    """
    await _on_event(
        db, _event(tenant_id=tenant_id, employee_id=None, full_name="Без Идентификатора")
    )
    await _on_event(
        db,
        DeletionEvent(
            seq=99,
            event_type="employee_updated",
            employee_id=uuid.uuid4(),
            tenant_id=None,
            created_at=dt.datetime.now(dt.UTC),
            full_name="Без Организации",
        ),
    )
    await _on_event(
        db,
        _event(
            tenant_id=tenant_id,
            employee_id=uuid.uuid4(),
            full_name="Что-то",
            event_type="employee_promoted_to_wizard",
        ),
    )

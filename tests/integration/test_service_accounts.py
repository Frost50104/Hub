"""Точка продаж — не ученик: карточка живёт, но из обучения исключена.

ОС владельца 16.09 по экрану «Прогресс сотрудников»: в списке людей стояли
«Волковский 30» и «Аптекарский проспект 5». Это учётные записи касс — общий
логин на планшете, в поле имени адрес. Auth размечает их `account_kind`, Hub с
0056 хранит вид и на тени, и на карточке.

Ключевая пара тестов здесь — `test_recalc_profile_removes_membership` и
`test_card_without_shadow_stays_person`. Первый закрывает мину: `load_attrs_map`
кассу отфильтровывает, и `recalc_profile` попал бы в ветку «гонка: профиль
архивирован», выйдя НЕ удалив членство, — на проде так повисли бы 220 строк.
Второй фиксирует решение: карточку, про которую auth не знает, мы НЕ прячем —
это не касса, а бесхозная HR-карточка, и её надо разобрать руками.
"""

from __future__ import annotations

import uuid

import pytest
from signaris_auth import Principal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.employees import list_employees, list_unlinked_logins
from app.api.learn_analytics import employee_progress, employee_progress_detail
from app.models.audience import Audience, AudienceMember, AudienceRule
from app.models.employee_profile import EmployeeProfile
from app.models.org import Position
from app.models.shadow import ShadowUser
from app.services.audience_resolver import (
    dimension_counts,
    load_attrs_map,
    rebuild_tenant,
    recalc_profile,
)
from tests.integration.conftest import make_principal

pytestmark = pytest.mark.integration


async def _admin(db: AsyncSession, tenant_id: uuid.UUID, email: str) -> Principal:
    principal = make_principal(
        tenant_id, email=email, role="admin", tenant_slug=f"t-{tenant_id.hex[:12]}"
    )
    from signaris_auth.shadow import upsert_shadow_tenant, upsert_shadow_user

    await upsert_shadow_tenant(db, principal, table="shadow_tenants")
    await upsert_shadow_user(db, principal, table="shadow_users")
    return principal


async def _profile(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    name: str,
    email: str,
    kind: str = "person",
    position_id: uuid.UUID | None = None,
    with_shadow: bool = True,
) -> EmployeeProfile:
    employee_id = uuid.uuid4() if with_shadow else None
    if with_shadow:
        # Тень flush'им ОТДЕЛЬНО: на `employee_profiles.employee_id` стоит FK,
        # и в общем flush порядок вставок не гарантирован.
        db.add(
            ShadowUser(
                employee_id=employee_id,
                tenant_id=tenant_id,
                email=email,
                full_name=name,
                account_kind=kind,
            )
        )
        await db.flush()
    profile = EmployeeProfile(
        tenant_id=tenant_id,
        employee_id=employee_id,
        email=email,
        full_name=name,
        account_kind=kind,
        position_id=position_id,
    )
    db.add(profile)
    await db.flush()
    return profile


async def _members(db: AsyncSession, profile_ids: list[uuid.UUID]) -> list[uuid.UUID]:
    """Членство в аудиториях ТОЛЬКО заданных профилей."""
    rows = await db.execute(
        select(AudienceMember.profile_id).where(
            AudienceMember.profile_id.in_(profile_ids)
        )
    )
    return sorted({r[0] for r in rows}, key=lambda x: profile_ids.index(x))


async def _employees(db: AsyncSession, principal: Principal):
    """Список сотрудников. Все параметры — явно: при прямом вызове ручки
    дефолтом стала бы сама `Query`, а не `None` (конвенция этого репозитория,
    см. `test_employee_list_paging`)."""
    return await list_employees(
        status_filter="active",
        q=None,
        store_id=None,
        position_id=None,
        limit=100,
        offset=0,
        principal=principal,
        db=db,
    )


# ─── Движок аудиторий ────────────────────────────────────────────────────────


async def test_service_card_is_not_a_candidate(db: AsyncSession, tenant_id: uuid.UUID):
    person = await _profile(db, tenant_id, name="Мария Иванова", email="m@t.ru")
    till = await _profile(
        db, tenant_id, name="Невская 3", email="n3@t.ru", kind="service"
    )
    attrs = await load_attrs_map(db)
    assert person.id in attrs
    assert till.id not in attrs, "касса не должна быть кандидатом в членство"


async def test_recalc_profile_removes_membership(db: AsyncSession, tenant_id: uuid.UUID):
    """Мина: без правки `recalc_profile` вышел бы по ветке «гонка», не удалив."""
    audience = Audience(tenant_id=tenant_id, is_all=True)
    db.add(audience)
    await db.flush()
    till = await _profile(db, tenant_id, name="Лыжный 8", email="l8@t.ru")
    await recalc_profile(db, till)
    assert (
        await db.execute(
            select(AudienceMember).where(AudienceMember.profile_id == till.id)
        )
    ).scalars().all(), "предусловие: касса сейчас в аудитории"

    # Auth сообщил, что это касса.
    till.account_kind = "service"
    await db.flush()
    await recalc_profile(db, till)

    left = (
        (
            await db.execute(
                select(AudienceMember).where(AudienceMember.profile_id == till.id)
            )
        )
        .scalars()
        .all()
    )
    assert left == [], "членство обязано сняться, а не повиснуть до полного пересчёта"


async def test_rebuild_clears_existing_membership(db: AsyncSession, tenant_id: uuid.UUID):
    """Уже накопленное членство вычищается полным пересчётом."""
    audience = Audience(tenant_id=tenant_id, is_all=True)
    db.add(audience)
    await db.flush()
    person = await _profile(db, tenant_id, name="Пётр Попов", email="p@t.ru")
    till = await _profile(db, tenant_id, name="Смоленка 35", email="s35@t.ru")
    mine = [person.id, till.id]
    await rebuild_tenant(db, tenant_id)
    # Считаем ТОЛЬКО своих: роль в testcontainers — superuser, она обходит RLS,
    # и в общем прогоне в таблице лежат профили соседних тестов.
    assert set(await _members(db, mine)) == set(mine), "предусловие: в аудитории оба"

    till.account_kind = "service"
    await db.flush()
    await rebuild_tenant(db, tenant_id)

    assert await _members(db, mine) == [person.id]


async def test_dimension_counts_ignore_tills(db: AsyncSession, tenant_id: uuid.UUID):
    """Счётчик «Увидят: N» в пикере аудиторий не должен быть раздут кассами."""
    position = Position(tenant_id=tenant_id, name="Продавец-бариста")
    db.add(position)
    await db.flush()
    await _profile(
        db, tenant_id, name="Анна Сидорова", email="a@t.ru", position_id=position.id
    )
    # Касса носит ТУ ЖЕ должность — на проде именно так и было.
    await _profile(
        db,
        tenant_id,
        name="Грибалевой 7",
        email="g7@t.ru",
        kind="service",
        position_id=position.id,
    )
    counts = await dimension_counts(db)
    assert counts["position_ids"][str(position.id)] == 1


async def test_sync_reclassification_drops_membership_immediately(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Синк пометил кассу — членство обязано уйти СРАЗУ, без кнопки.

    Поймано на проде 16.09: auth дораз­метил две точки сервисными, staff-sync
    карточки обновил, а 8 строк членства висели дальше — полного пересчёта по
    расписанию у нас нет, и узнать о зазоре было неоткуда.
    """
    from app.services.employee_profiles import ensure_profile_for_staff_row

    audience = Audience(tenant_id=tenant_id, is_all=True)
    db.add(audience)
    await db.flush()
    till = await _profile(db, tenant_id, name="Каменка 15", email="k15@t.ru")
    await recalc_profile(db, till)
    assert await _members(db, [till.id]) == [till.id], "предусловие: членство есть"

    # Прогон синка: auth сообщил, что это касса.
    outcome = await ensure_profile_for_staff_row(
        db,
        tenant_id=tenant_id,
        employee_id=till.employee_id,
        email="k15@t.ru",
        full_name="Каменка 15",
        link_only=True,
        account_kind="service",
    )
    assert outcome == "already_linked"

    await db.refresh(till)
    assert till.account_kind == "service"
    assert await _members(db, [till.id]) == [], "членство не должно ждать пересчёта"


# ─── Списки ──────────────────────────────────────────────────────────────────


async def test_tills_are_absent_from_employees_and_total(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """`total` обязан считаться ПОСЛЕ предиката, иначе подпись экрана соврёт."""
    admin = await _admin(db, tenant_id, "admin@t.ru")
    await _profile(db, tenant_id, name="Мария Иванова", email="m@t.ru")
    till = await _profile(db, tenant_id, name="Невская 3", email="n3@t.ru")

    before = await _employees(db, admin)
    assert "Невская 3" in {i.full_name for i in before.items}

    # Auth сообщил, что это касса.
    till.account_kind = "service"
    await db.flush()
    after = await _employees(db, admin)

    assert "Невская 3" not in {i.full_name for i in after.items}
    assert "Мария Иванова" in {i.full_name for i in after.items}
    # Ключевое: `total` уменьшился вместе со строкой. Считался бы он ДО
    # предиката — подпись экрана навсегда ушла бы в «Показаны N из M,
    # уточните поиск» (employeeListCaption срабатывает при shown < total).
    assert after.total == before.total - 1


async def test_till_shadow_is_not_an_unlinked_problem(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Касса без карточки — штатное состояние, а не «опечатка в email»."""
    admin = await _admin(db, tenant_id, "admin2@t.ru")
    db.add(
        ShadowUser(
            employee_id=uuid.uuid4(),
            tenant_id=tenant_id,
            email="m14@t.ru",
            full_name="Михайловская 14",
            account_kind="service",
        )
    )
    human = uuid.uuid4()
    db.add(
        ShadowUser(
            employee_id=human,
            tenant_id=tenant_id,
            email="human@t.ru",
            full_name="Человек Без Карточки",
            account_kind="person",
        )
    )
    await db.flush()

    emails = {r.email for r in await list_unlinked_logins(principal=admin, db=db)}
    assert "human@t.ru" in emails, "человек без карточки — это проблема, её показываем"
    assert "m14@t.ru" not in emails, "касса без карточки — норма, а не опечатка"


async def test_tills_are_absent_from_progress(db: AsyncSession, tenant_id: uuid.UUID):
    admin = await _admin(db, tenant_id, "admin3@t.ru")
    await _profile(db, tenant_id, name="Мария Иванова", email="m@t.ru")
    till = await _profile(
        db, tenant_id, name="Невская 3", email="n3@t.ru", kind="service"
    )
    res = await employee_progress(principal=admin, db=db)
    assert till.id not in {r.profile_id for r in res.items}
    assert res.total == len(res.items)


async def test_detail_of_a_till_still_answers(db: AsyncSession, tenant_id: uuid.UUID):
    """Спросили про конкретную карточку — отвечаем, какого бы она ни была вида.

    Предикат в ветке по явным id дал бы здесь IndexError, то есть 500.
    """
    admin = await _admin(db, tenant_id, "admin4@t.ru")
    till = await _profile(
        db, tenant_id, name="Невская 3", email="n3@t.ru", kind="service"
    )
    detail = await employee_progress_detail(till.id, principal=admin, db=db)
    assert detail.profile.profile_id == till.id


# ─── Сироты ──────────────────────────────────────────────────────────────────


async def test_card_without_shadow_stays_person(db: AsyncSession, tenant_id: uuid.UUID):
    """Карточка, про которую auth не знает, остаётся человеком.

    Это решение, а не недоработка: такую карточку надо разобрать руками, а не
    спрятать. Признак ей проставляет разовая джоба явным списком id.
    """
    admin = await _admin(db, tenant_id, "admin5@t.ru")
    orphan = await _profile(
        db, tenant_id, name="Кондратьевский, 18", email="k18@t.ru", with_shadow=False
    )
    res = await _employees(db, admin)
    assert orphan.id in {i.id for i in res.items}


# ─── Рассылки и рейтинг ──────────────────────────────────────────────────────


async def test_broadcast_audience_excludes_tills(db: AsyncSession, tenant_id: uuid.UUID):
    """Ветка «видно всем» членство не читает — предикат нужен и там."""
    from app.api.library import _audience_profile_ids

    person = await _profile(db, tenant_id, name="Мария Иванова", email="m@t.ru")
    till = await _profile(
        db, tenant_id, name="Невская 3", email="n3@t.ru", kind="service"
    )
    ids = await _audience_profile_ids(db, None)
    assert person.id in ids
    assert till.id not in ids


async def test_audience_rules_still_work_for_people(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Проверка, что предикат не сломал адресные аудитории."""
    position = Position(tenant_id=tenant_id, name="Офис")
    db.add(position)
    await db.flush()
    audience = Audience(tenant_id=tenant_id)
    db.add(audience)
    await db.flush()
    db.add(
        AudienceRule(
            tenant_id=tenant_id,
            audience_id=audience.id,
            mode="include",
            position_ids=[position.id],
        )
    )
    person = await _profile(
        db, tenant_id, name="Дудин Никита", email="d@t.ru", position_id=position.id
    )
    await db.flush()
    await rebuild_tenant(db, tenant_id)
    assert await _members(db, [person.id]) == [person.id]


# --- claim `signaris:account_kind` в токене (auth, 16.09 20:50 UTC) ----------
#
# Зазор, который claim закрывает: точка С РОЛЬЮ hub открыла Hub раньше тика
# синка (до 15 минут; на staging синка нет вовсе) — до правки она получала
# карточку `person`, членство и пуши «назначен курс» на кассу. Выгрузка штата
# при этом остаётся главной: claim работает ТОЛЬКО там, где выгрузка учётку
# ещё не видела (`staff_synced_at IS NULL`).


async def _shadow(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    email: str,
    name: str,
    kind: str | None,
    synced: bool,
) -> uuid.UUID:
    """Тень как её заводит client-lib на первом же запросе. `synced` — видел ли
    строку прогон выгрузки (именно это, а не свежесть снимка, решает спор)."""
    from datetime import UTC, datetime

    employee_id = uuid.uuid4()
    db.add(
        ShadowUser(
            employee_id=employee_id,
            tenant_id=tenant_id,
            email=email,
            full_name=name,
            account_kind=kind,
            staff_synced_at=datetime.now(UTC) if synced else None,
        )
    )
    await db.flush()
    return employee_id


def _principal(
    tenant_id: uuid.UUID, employee_id: uuid.UUID, email: str, name: str, **extra
) -> Principal:
    return Principal(
        employee_id=employee_id,
        email=email,
        tenant_id=tenant_id,
        tenant_slug="test",
        full_name=name,
        product_roles={"hub": "member"},
        jti=str(uuid.uuid4()),
        **extra,
    )


async def _login(db: AsyncSession, principal: Principal, monkeypatch) -> tuple:
    """Первый вход. Возвращает (карточка, сколько членств ПРИБАВИЛОСЬ).

    Считаем именно прибавленное, а не число вызовов notify: вызов стоит в
    общем пути безусловно, а `notify_new_audience_members` на пустом `added`
    выходит первой же строкой. Рассылку порождает granted_at нового членства,
    поэтому ноль здесь и означает «кассе ничего не ушло».
    """
    from app.services import employee_profiles as ep

    added = 0

    async def _spy(db_, diffs):
        nonlocal added
        added += sum(len(d.added) for d in diffs.values())

    monkeypatch.setattr(ep, "notify_new_audience_members", _spy)
    result = await ep.ensure_profile_for_principal(db, principal)
    return result.profile, added


async def test_service_claim_blocks_learner_card(
    db: AsyncSession, tenant_id: uuid.UUID, monkeypatch
):
    """(а) Первый вход кассы с ролью hub: карточка служебная, notify молчит."""
    db.add(Audience(tenant_id=tenant_id))  # аудитория «всем» — контроль
    await db.flush()

    employee_id = await _shadow(
        db, tenant_id, email="k19@t.ru", name="Кондратьевский, 19", kind=None, synced=False
    )
    principal = _principal(
        tenant_id, employee_id, "k19@t.ru", "Кондратьевский, 19", account_kind="service"
    )
    profile, granted = await _login(db, principal, monkeypatch)

    assert profile is not None
    assert profile.account_kind == "service"
    assert await _members(db, [profile.id]) == []
    assert granted == 0, "кассе прибавилось членство — уйдут пуши о курсах"


async def test_person_login_unaffected_by_claim_work(
    db: AsyncSession, tenant_id: uuid.UUID, monkeypatch
):
    """Контроль к (а): человек тем же путём карточку и членство получает."""
    db.add(Audience(tenant_id=tenant_id))
    await db.flush()

    employee_id = await _shadow(
        db, tenant_id, email="ivanova@t.ru", name="Иванова Мария", kind=None, synced=False
    )
    principal = _principal(
        tenant_id, employee_id, "ivanova@t.ru", "Иванова Мария", account_kind="person"
    )
    profile, granted = await _login(db, principal, monkeypatch)

    assert profile.account_kind == "person"
    assert await _members(db, [profile.id]) == [profile.id]
    # `>= 1`, а не `== 1`: роль testcontainers — суперюзер, RLS её не режет, и
    # аудитории, закоммиченные соседними тестами, живут в том же тенанте. У
    # кассы ноль остаётся нолём при любом их числе, а здесь важен сам факт —
    # человек членство получил, то есть предикат не задел живых людей.
    assert granted >= 1


async def test_token_without_claim_behaves_as_before(
    db: AsyncSession, tenant_id: uuid.UUID, monkeypatch
):
    """(б) Токен без claim'а — старый бандл, откат auth, поля нет в контракте.

    Отсутствие ключа значит «не знаю», а НЕ `service`: fail-open, иначе откат
    auth разом превратил бы всех входящих в служебные учётки.
    """
    employee_id = await _shadow(
        db, tenant_id, email="petrov@t.ru", name="Петров Иван", kind=None, synced=False
    )
    principal = _principal(tenant_id, employee_id, "petrov@t.ru", "Петров Иван")
    assert getattr(principal, "account_kind", None) is None

    profile, _ = await _login(db, principal, monkeypatch)
    assert profile.account_kind == "person"


async def test_claim_never_rewrites_existing_card(
    db: AsyncSession, tenant_id: uuid.UUID, monkeypatch
):
    """(в) `person` в токене против карточки, размеченной синком служебной.

    Вид существующей карточки меняет ТОЛЬКО синк. Иначе устаревший токен (до
    15 минут) спорил бы с выгрузкой, и каждый откат в `person` заново слал бы
    кассе пуши о курсах.
    """
    till = await _profile(db, tenant_id, name="Волковский 30", email="v30@t.ru", kind="service")
    await db.flush()
    principal = _principal(
        tenant_id, till.employee_id, "v30@t.ru", "Волковский 30", account_kind="person"
    )

    profile, granted = await _login(db, principal, monkeypatch)
    assert profile.id == till.id
    assert profile.account_kind == "service", "claim переписал вид существующей карточки"
    assert granted == 0


async def test_staff_feed_beats_claim_for_new_card(
    db: AsyncSession, tenant_id: uuid.UUID, monkeypatch
):
    """Спор выгрузки и токена решается в пользу выгрузки.

    Тень уже прошла через прогон штата и размечена служебной, а токен на руках
    старый и говорит `person`. Карточки ещё нет — и завести её человеком было
    бы регрессом ровно в тот баг, который чиним.
    """
    employee_id = await _shadow(
        db, tenant_id, email="a5@t.ru", name="Аптекарский 5", kind="service", synced=True
    )
    principal = _principal(
        tenant_id, employee_id, "a5@t.ru", "Аптекарский 5", account_kind="person"
    )
    profile, granted = await _login(db, principal, monkeypatch)

    assert profile.account_kind == "service"
    assert granted == 0


def test_unknown_kind_maps_to_service():
    """Третий вид из auth не должен ронять запись: CHECK знает только два.

    Юнит-часть — в CI бегут только такие: интеграционные там не запускаются.
    """
    from app.services.employee_profiles import normalize_account_kind

    assert normalize_account_kind("person") == "person"
    assert normalize_account_kind("service") == "service"
    assert normalize_account_kind("bot") == "service"
    assert normalize_account_kind("kiosk-terminal-extended") == "service"
    assert normalize_account_kind(None) == "person"

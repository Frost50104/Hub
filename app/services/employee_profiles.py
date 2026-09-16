"""HR-профили: матчинг с auth-аккаунтом, архивация, восстановление (Ф0 LMS).

Матчинг (вызывается из /api/me ТОЛЬКО для principals с hub-ролью — иначе
юзеры других продуктов Signaris засоряли бы оргструктуру):
1. профиль уже привязан по employee_id → синк email при расхождении;
2. активный профиль с тем же lower(email) без привязки → привязать;
3. АРХИВНЫЙ профиль с тем же email (повторный найм) → НЕ создавать дубль,
   вернуть needs_restore — админ восстанавливает через re-link;
4. ничего → создать минимальный профиль (email+ФИО из JWT), HR дозаполнит.

Гонка первого входа гасится partial-unique (tenant_id, lower(email)) WHERE
status='active' + INSERT ON CONFLICT DO NOTHING + повторный SELECT.

Архивация — единый каскад для увольнения/неактивности/deletion-sync:
статус + вычистка audience_members (+ с Ф5 — cancel automation_jobs).
История обучения не удаляется никогда (ТЗ §23).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

import structlog
from signaris_auth import Principal
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employee_profile import EmployeeProfile
from app.models.shadow import ShadowUser
from app.services import audit
from app.services.audience_resolver import recalc_profile
from app.services.learn_notify import notify_new_audience_members

log = structlog.get_logger("employee_profiles")

ACCOUNT_KINDS = ("person", "service")


def normalize_account_kind(value: str | None) -> str:
    """Привести вид учётки к тому, что физически влезает в схему.

    На карточке стоит CHECK IN ('person','service'), а вид приезжает из auth —
    из выгрузки штата и (с 16.09) из claim'а токена. Появись там третье
    значение, незнакомое нам, запись карточки упала бы IntegrityError и
    откатила ВЕСЬ прогон синка — каждые 15 минут, до выката. Поэтому всё, что
    не `person`, считаем служебным: для learn-домена важна ровно эта граница
    («учится» / «не учится»), и ошибиться в сторону «не учится» безопаснее —
    лишняя рассылка курсов на кассу необратима, а её отсутствие чинится.

    `None` — это «не знаю» (старый токен, откат auth, поля нет в контракте), и
    оно даёт `person`: fail-open, тот же довод, что у `staff_snapshot_fresh` —
    иначе пропажа признака разом опустошила бы все экраны.
    """
    if value is None:
        return "person"
    return value if value in ACCOUNT_KINDS else "service"


def _kind_for_new_profile(shadow: ShadowUser | None, claim: str | None) -> str:
    """Вид для карточки, которой ещё нет: выгрузка штата > claim токена.

    Выгрузка выигрывает всегда, и условие «она эту учётку видела» — именно
    `staff_synced_at IS NOT NULL`, а не свежесть снимка: свежесть отвечает на
    другой вопрос («не протух ли снимок целиком»). Claim нужен ровно в зазоре,
    которого выгрузка закрыть не может: точка с ролью hub, открывшая Hub
    раньше ближайшего тика синка (до 15 минут; на staging синка нет вовсе).
    """
    if shadow is not None and shadow.staff_synced_at is not None:
        return normalize_account_kind(shadow.account_kind)
    return normalize_account_kind(claim)


def normalize_email(email: str) -> str:
    return email.strip().lower()


@dataclass
class MatchResult:
    outcome: Literal["linked", "created", "needs_restore", "already_linked"]
    profile: EmployeeProfile | None


async def _find_by_employee_id(db: AsyncSession, employee_id: UUID) -> EmployeeProfile | None:
    return (
        await db.execute(
            select(EmployeeProfile).where(EmployeeProfile.employee_id == employee_id)
        )
    ).scalar_one_or_none()


async def _find_by_email(
    db: AsyncSession, email: str, *, status: str
) -> EmployeeProfile | None:
    return (
        await db.execute(
            select(EmployeeProfile).where(
                func.lower(EmployeeProfile.email) == normalize_email(email),
                EmployeeProfile.status == status,
            )
        )
    ).scalar_one_or_none()


async def find_latest_archived_by_email(
    db: AsyncSession, email: str
) -> EmployeeProfile | None:
    """Самая свежая АРХИВНАЯ карточка с этим адресом.

    Отдельно от `_find_by_email` и с `.first()` вместо `scalar_one_or_none()`
    намеренно. У активных стоит partial-unique индекс, и вторая строка там —
    повод упасть; у архивных индекса нет, а с 01.09 повторный найм создаёт
    НОВУЮ карточку вместо восстановления старой. Значит цепочка «наняли —
    уволили — наняли — уволили» даёт две архивные записи на один адрес, и
    `scalar_one_or_none()` бросил бы `MultipleResultsFound` прямо в `/api/me`:
    человек не смог бы войти в Hub вообще.
    """
    return (
        await db.execute(
            select(EmployeeProfile)
            .where(
                func.lower(EmployeeProfile.email) == normalize_email(email),
                EmployeeProfile.status == "archived",
            )
            .order_by(EmployeeProfile.archived_at.desc().nulls_last())
            .limit(1)
        )
    ).scalars().first()


async def ensure_profile_for_principal(db: AsyncSession, principal: Principal) -> MatchResult:
    """Идемпотентный матчинг/создание профиля. Коммитит вызывающий."""
    now = datetime.now(UTC)

    existing = await _find_by_employee_id(db, principal.employee_id)
    if existing is not None:
        await _sync_linked_profile(db, existing, principal, now)
        return MatchResult(outcome="already_linked", profile=existing)

    email = normalize_email(principal.email)

    active = await _find_by_email(db, email, status="active")
    if active is not None:
        if active.employee_id is None:
            # Guard в WHERE — параллельный запрос не перепривяжет чужой профиль.
            result = await db.execute(
                update(EmployeeProfile)
                .where(EmployeeProfile.id == active.id, EmployeeProfile.employee_id.is_(None))
                .values(employee_id=principal.employee_id, last_activity_at=now)
            )
            if result.rowcount:
                log.info("profile.linked", profile_id=str(active.id))
                await db.refresh(active)
                # Имя и email зеркалим СРАЗУ при привязке, а не со второго
                # входа. Иначе HR-написание застревает в карточке, а починить
                # его уже нечем: `last_activity_at` только что выставлен, и
                # PATCH этих полей отвечает 422 (ОС 28.08, случай rfedorov1@).
                await _sync_linked_profile(db, active, principal, now)
                await db.refresh(active)
                diffs = await recalc_profile(db, active)
                await notify_new_audience_members(db, diffs)
                return MatchResult(outcome="linked", profile=active)
            existing = await _find_by_employee_id(db, principal.employee_id)
            return MatchResult(outcome="already_linked", profile=existing)
        # Активный профиль с этим email принадлежит другому auth-аккаунту —
        # в auth email уникален, значит это рассинхрон данных. Не трогаем.
        log.warning(
            "profile.email_conflict",
            email=email,
            profile_id=str(active.id),
        )
        return MatchResult(outcome="needs_restore", profile=None)

    # Архивную карточку с этим адресом СОЗНАТЕЛЬНО не подхватываем (01.09).
    # Раньше здесь возвращался `needs_restore`, и админ видел одну кнопку
    # «восстановить» — то есть «отдать новому человеку историю старого». А
    # корпоративный ящик уволенного отдают следующему сотруднику, и он получал
    # чужие сертификаты и сданные курсы. Теперь заводим ЧИСТУЮ карточку;
    # вернувшийся сотрудник по умолчанию проходит обучение заново, а свести две
    # карточки вручную admin по-прежнему может через `/restore`.
    twin = await find_latest_archived_by_email(db, email)

    # Вид НОВОЙ карточки. До 16.09 он здесь не считался вовсе — карточка
    # рождалась с дефолтом `person`, и точка с ролью hub, зашедшая раньше тика
    # синка, получала обычную учебную карточку: `recalc_profile` ниже выдавал
    # ей членство, `notify_new_audience_members` слал пуши о курсах НА КАССУ.
    # Разбор auth 16.09 («Где claim вам действительно нужен»): это основной
    # путь заведения точки, а не редкий угол.
    #
    # Вид пишется В ТОТ ЖЕ INSERT — обязательно ДО `recalc_profile`: тот
    # смотрит `profile.account_kind` и на служебной карточке уходит в ветку
    # снятия членства, то есть diffs пустые и уведомлять нечего. Отдельным
    # UPDATE после вставки этого не добиться: между ними уже уйдут пуши.
    #
    # Карточку служебной учётке всё же ЗАВОДИМ (а не отказываем, как делает
    # `link_only` у синка): решение владельца 04.09 — карточки кафе остаются,
    # на кассе точки открыт её аккаунт, и непривязанная карточка показывала
    # «без учётки» при живой учётке в auth. Меняем вид, а не факт заведения.
    shadow = (
        await db.execute(
            select(ShadowUser).where(ShadowUser.employee_id == principal.employee_id)
        )
    ).scalar_one_or_none()
    kind = _kind_for_new_profile(shadow, getattr(principal, "account_kind", None))

    stmt = (
        pg_insert(EmployeeProfile)
        .values(
            tenant_id=principal.tenant_id,
            employee_id=principal.employee_id,
            email=email,
            full_name=principal.full_name,
            last_activity_at=now,
            account_kind=kind,
        )
        .on_conflict_do_nothing(
            index_elements=["tenant_id", func.lower(EmployeeProfile.email)],
            index_where=EmployeeProfile.status == "active",
        )
        .returning(EmployeeProfile.id)
    )
    inserted_id = (await db.execute(stmt)).scalar_one_or_none()
    if inserted_id is None:
        # Гонка: параллельный запрос успел первым — читаем его результат.
        profile = await _find_by_email(db, email, status="active")
        return MatchResult(outcome="already_linked", profile=profile)
    profile = (
        await db.execute(select(EmployeeProfile).where(EmployeeProfile.id == inserted_id))
    ).scalar_one()
    # Членство сразу: is_all/exclude-only аудитории должны включить новичка.
    diffs = await recalc_profile(db, profile)
    await notify_new_audience_members(db, diffs)
    log.info("profile.autocreated", profile_id=str(inserted_id), email=email)
    if twin is not None:
        # Обычно это новый человек на освободившемся ящике — всё правильно. Но
        # тем же путём проходит ОШИБОЧНАЯ архивация: человека убрали по недосмотру,
        # он вошёл и получил дубль, а история осталась в архиве. Снятая ветка
        # `needs_restore` была единственным сигналом об этом, поэтому оставляем
        # след — и в аудите, и полем `archived_twin` на карточке.
        audit.record(
            db,
            tenant_id=profile.tenant_id,
            actor_id=principal.employee_id,
            action="create",
            object_type="employee_profile",
            object_id=profile.id,
            object_label=profile.full_name,
            diff={"archived_twin": {"old": None, "new": str(twin.id)}},
        )
        log.info(
            "profile.autocreated_with_archived_twin",
            profile_id=str(inserted_id),
            twin_id=str(twin.id),
        )
    return MatchResult(outcome="created", profile=profile)


StaffRowOutcome = Literal[
    "already_linked", "linked", "created", "email_conflict", "archived_skip", "no_card"
]


async def ensure_profile_for_staff_row(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    employee_id: UUID,
    email: str,
    full_name: str,
    link_only: bool = False,
    account_kind: str = "person",
) -> StaffRowOutcome:
    """Матчинг/создание карточки из PULL-строки штата (staff-sync, 0052).

    `link_only=True` — режим сервисных учёток (решение владельца 04.09):
    существующую карточку ПРИВЯЗЫВАЕМ (непривязанная карточка кафе показывала
    «без учётки» при живой учётке в auth), но НЕ создаём (`no_card`) — гейт
    требования 1 остаётся на создании, ветка привязки уведомлений не шлёт.

    Тот же порядок, что у `ensure_profile_for_principal` (employee_id →
    lower(email) среди active → создание), с тремя намеренными отличиями:
    - `last_activity_at` НЕ ставится: человек не входил, бейдж «не входил»
      и заморозка идентичности обязаны работать как для не входивших;
    - `_sync_linked_profile` не зовётся: он ставит last_activity_at, а имя
      привязанной HR-карточки до первого входа остаётся редактируемым
      (та же семантика, что у ручки /link);
    - архивная карточка с тем же email БЛОКИРУЕТ создание (`archived_skip`,
      требование 3 auth): `archive_profile(manual)` обнуляет employee_id, и
      без этой проверки pull пересоздавал бы карточку через 15 минут после
      каждой ручной архивации — с новой рассылкой обязательных курсов.
      Настоящий новый человек на освободившемся ящике карточку всё равно
      получит — при первом ВХОДЕ (`ensure_profile_for_principal` архивных
      сознательно не смотрит и заводит чистую с подсказкой archived_twin).
      Автоархив (`auto_inactivity`) сюда не доходит: он сохраняет
      employee_id, и `_find_by_employee_id` возвращает already_linked.

    Гонки с живым входом закрыты теми же механизмами, что и там: UPDATE с
    guard `employee_id IS NULL` и partial-UNIQUE (tenant_id, lower(email))
    WHERE status='active'.
    """
    from app.services.audience_resolver import recalc_profile

    # Нормализуем на границе записи, а не у вызывающего: эту функцию зовёт и
    # синк, и тесты, и любой будущий код, а CHECK на колонке один на всех.
    account_kind = normalize_account_kind(account_kind)

    existing = await _find_by_employee_id(db, employee_id)
    if existing is not None:
        # Вид карточки сверяем ДАЖЕ у уже привязанной — иначе признак был бы
        # неполучаемым: на проде 54 карточки-кассы из 55 уже привязаны, и эта
        # ветка возвращала бы `already_linked` до любой записи. Так синк лечит
        # себя сам, а разовый бэкфилл нужен только тем, у кого тени нет.
        if existing.account_kind != account_kind:
            await db.execute(
                update(EmployeeProfile)
                .where(EmployeeProfile.id == existing.id)
                .values(account_kind=account_kind)
            )
            existing.account_kind = account_kind
            # Членство обязано поехать СРАЗУ за видом, а не ждать кнопки
            # «Пересчитать доступы». Ровно этот зазор поймали на проде 16.09:
            # auth пометил две кассы сервисными, синк карточки обновил, а 8
            # строк членства висели дальше — и узнать об этом было неоткуда,
            # полного пересчёта по расписанию у нас нет. Пересчёт точечный
            # (`recalc_profile`), и он срабатывает только при СМЕНЕ вида:
            # на обычном прогоне, где ничего не поменялось, лишнего lock'а нет.
            await recalc_profile(db, existing)
            log.info(
                "staff_sync.account_kind_synced",
                profile_id=str(existing.id),
                account_kind=account_kind,
            )
        return "already_linked"

    norm = normalize_email(email)
    active = await _find_by_email(db, norm, status="active")
    if active is not None:
        if active.employee_id is None:
            result = await db.execute(
                update(EmployeeProfile)
                .where(EmployeeProfile.id == active.id, EmployeeProfile.employee_id.is_(None))
                .values(employee_id=employee_id, account_kind=account_kind)
            )
            if result.rowcount:
                log.info("staff_sync.profile_linked", profile_id=str(active.id))
                return "linked"
            return "already_linked"
        # Активная карточка с этим email привязана к другому auth-аккаунту —
        # рассинхрон данных, руками через /link или /restore. Не трогаем.
        log.warning("staff_sync.email_conflict", email=norm, profile_id=str(active.id))
        return "email_conflict"

    if link_only:
        return "no_card"

    twin = await find_latest_archived_by_email(db, norm)
    if twin is not None:
        log.info("staff_sync.archived_skip", twin_id=str(twin.id))
        return "archived_skip"

    stmt = (
        pg_insert(EmployeeProfile)
        .values(
            tenant_id=tenant_id,
            employee_id=employee_id,
            email=norm,
            full_name=full_name or norm,
        )
        .on_conflict_do_nothing(
            index_elements=["tenant_id", func.lower(EmployeeProfile.email)],
            index_where=EmployeeProfile.status == "active",
        )
        .returning(EmployeeProfile.id)
    )
    inserted_id = (await db.execute(stmt)).scalar_one_or_none()
    if inserted_id is None:
        return "already_linked"  # гонка: параллельный вход успел первым
    profile = (
        await db.execute(select(EmployeeProfile).where(EmployeeProfile.id == inserted_id))
    ).scalar_one()
    # Членство сразу: is_all/exclude-only аудитории должны включить новичка
    # (и уведомить об обязательных материалах — как при ручном заведении).
    diffs = await recalc_profile(db, profile)
    await notify_new_audience_members(db, diffs)
    log.info("staff_sync.profile_created", profile_id=str(inserted_id), email=norm)
    return "created"


async def classify_staff_row(
    db: AsyncSession,
    *,
    employee_id: UUID,
    email: str,
    link_only: bool = False,
) -> StaffRowOutcome:
    """Read-only предсказание исхода `ensure_profile_for_staff_row` — dry-run.

    Отдельная функция, а не «прогон + rollback»: у живого пути есть побочка
    вне транзакции (`notify_new_audience_members` шлёт реальные пуши), и
    откат БД её не отменил бы. Порядок веток обязан совпадать с живым путём.
    """
    if await _find_by_employee_id(db, employee_id) is not None:
        return "already_linked"
    norm = normalize_email(email)
    active = await _find_by_email(db, norm, status="active")
    if active is not None:
        return "linked" if active.employee_id is None else "email_conflict"
    if link_only:
        return "no_card"
    if await find_latest_archived_by_email(db, norm) is not None:
        return "archived_skip"
    return "created"


async def _sync_linked_profile(
    db: AsyncSession,
    profile: EmployeeProfile,
    principal: Principal,
    now: datetime,
) -> None:
    values: dict = {"last_activity_at": now}

    # Имя принадлежит auth: профиль его ЗЕРКАЛИТ, а не хранит своё (ОС 28.08 —
    # HR переименовал человека на экране «Сотрудники», а в пикере участников
    # осталось старое: трекер читает shadow_users, learn — профиль, и хозяева у
    # них были разные). Пустое имя из токена НЕ затирает существующее: в
    # профиле это единственный опознавательный признак в списках, а JWT
    # приходит извне.
    new_name = (principal.full_name or "").strip()
    if new_name and new_name != profile.full_name:
        audit.record(
            db,
            tenant_id=profile.tenant_id,
            actor_id=principal.employee_id,
            action="update",
            object_type="employee_profile",
            object_id=profile.id,
            object_label=new_name,
            diff={"full_name": {"old": profile.full_name, "new": new_name}},
        )
        values["full_name"] = new_name

    new_email = normalize_email(principal.email)
    if normalize_email(profile.email) != new_email:
        # Смена email в auth. Pre-check вместо ловли IntegrityError — ошибка
        # уникальности убила бы всю транзакцию запроса.
        holder = await _find_by_email(db, new_email, status="active")
        if holder is None or holder.id == profile.id:
            audit.record(
                db,
                tenant_id=profile.tenant_id,
                actor_id=principal.employee_id,
                action="update",
                object_type="employee_profile",
                object_id=profile.id,
                object_label=profile.full_name,
                diff={"email": {"old": profile.email, "new": new_email}},
            )
            values["email"] = new_email
        else:
            log.warning(
                "profile.email_sync_conflict",
                profile_id=str(profile.id),
                new_email=new_email,
                holder_id=str(holder.id),
            )
    await db.execute(
        update(EmployeeProfile).where(EmployeeProfile.id == profile.id).values(**values)
    )


# Причины, по которым карточка ОСВОБОЖДАЕТ вход: архивировал человек (`manual`)
# или учётку удалили в auth (`auth_deleted`).
#
# Спрашивать админа «уволен или временно?» мы пробовали и отказались: выбор
# можно ответить неверно КАЖДЫЙ раз, а неверный ответ бесшумно возвращает
# исходный баг — ящик остаётся занятым, и следующий сотрудник наследует чужую
# карточку. Непрерывность при этом ничего не теряет: архивная карточка
# блокирует обучение независимо от привязки, восстанавливать её админу
# приходится в любом случае, а восстановленная БЕЗ привязки заново связывается
# по email на следующем входе (ветка «активная без привязки» ниже).
#
# `auto_inactivity` — единственное исключение, и оно не про выбор: джоба
# архивирует человека, который никуда не уходил, просто полгода не заходил.
# Отвязка выкинула бы действующего сотрудника в «Непривязанные входы».
UNBINDING_REASONS = ("manual", "auth_deleted")


async def archive_profile(
    db: AsyncSession,
    profile: EmployeeProfile,
    *,
    reason: str,
    actor_id: UUID | None,
) -> None:
    """Единый каскад архивации. Идемпотентен (уже архивный → no-op)."""
    if profile.status == "archived":
        return
    profile.status = "archived"
    profile.archived_at = datetime.now(UTC)
    profile.archive_reason = reason
    if reason in UNBINDING_REASONS:
        # Освобождаем вход и корпоративный ящик: следующий сотрудник на том же
        # адресе не найдётся ни по `employee_id`, ни по email и получит чистую
        # карточку. История остаётся здесь, на архивной (ОС владельца 01.09 —
        # «новый получает остаток от уволенного»).
        profile.employee_id = None
    await db.flush()
    # Каскад: членства аудиторий (recalc_profile для archived удаляет все).
    await recalc_profile(db, profile)
    # Каскад Ф5: pending-автосценарии отменяются (курс не назначится вдогонку).
    from sqlalchemy import update

    from app.models.automation import AutomationJob

    await db.execute(
        update(AutomationJob)
        .where(
            AutomationJob.profile_id == profile.id,
            AutomationJob.status == "pending",
        )
        .values(status="cancelled")
    )
    audit.record(
        db,
        tenant_id=profile.tenant_id,
        actor_id=actor_id,
        action="archive",
        object_type="employee_profile",
        object_id=profile.id,
        object_label=profile.full_name,
        diff={"reason": {"old": None, "new": reason}},
    )
    log.info("profile.archived", profile_id=str(profile.id), reason=reason)


async def restore_profile(
    db: AsyncSession,
    profile: EmployeeProfile,
    *,
    actor_id: UUID | None,
    new_employee_id: UUID | None = None,
) -> None:
    """Восстановление из архива, опционально с перепривязкой к новому
    auth-аккаунту (повторный найм: в auth у человека новый employee_id)."""
    if profile.status == "active":
        return
    dup = await _find_by_email(db, profile.email, status="active")
    if dup is not None:
        raise ValueError(
            f"Активный профиль с email {profile.email} уже существует — "
            "восстановление создаст дубль."
        )
    if new_employee_id is not None:
        holder = await _find_by_employee_id(db, new_employee_id)
        if holder is not None and holder.id != profile.id:
            raise ValueError("Этот вход уже привязан к другой карточке.")
        profile.employee_id = new_employee_id
    profile.status = "active"
    profile.archived_at = None
    profile.archive_reason = None
    await db.flush()
    diffs = await recalc_profile(db, profile)
    await notify_new_audience_members(db, diffs)
    audit.record(
        db,
        tenant_id=profile.tenant_id,
        actor_id=actor_id,
        action="restore",
        object_type="employee_profile",
        object_id=profile.id,
        object_label=profile.full_name,
    )
    log.info("profile.restored", profile_id=str(profile.id))

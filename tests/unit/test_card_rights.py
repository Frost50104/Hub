"""Права по данным карточки — только активной карточке человека (21.10).

HUB_TASK_account_kind_switch: касса (`account_kind='service'`, общий логин
планшета точки) с копией контура, франчайзи, точек ТУ или контент-роли
человека прав по ним не получает. Тесты без БД — бегут в CI, где
интеграционные не гоняются; корни проверяются на подменах `get_profile`.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from signaris_auth import Principal

from app.api import reports
from app.services import content_access, org_scope, project_access
from app.services.employee_profiles import access_grant_fields
from app.services.org_scope import (
    card_grants_rights,
    effective_content_role,
    effective_org_role,
)


def _p(role: str = "member", account_kind: str | None = None) -> Principal:
    return Principal(
        employee_id=uuid.uuid4(),
        email="u@t.ru",
        tenant_id=uuid.uuid4(),
        tenant_slug="t",
        full_name="U",
        product_roles={"hub": role},
        jti=str(uuid.uuid4()),
        account_kind=account_kind,
    )


def _card(**kw: object) -> SimpleNamespace:
    base: dict[str, object] = {
        "id": uuid.uuid4(),
        "status": "active",
        "account_kind": "person",
        "org_role": "employee",
        "content_role": "none",
        "franchisee_id": None,
    }
    base.update(kw)
    return SimpleNamespace(**base)


class _Result:
    def __init__(self, row: object) -> None:
        self._row = row

    def first(self) -> object:
        return self._row

    def one_or_none(self) -> object:
        return self._row


class _DB:
    """Один ответ на любой запрос: строка для `.first()`/`.one_or_none()`
    или готовый список строк для перебора."""

    def __init__(self, row: object = None, rows: list[tuple] | None = None) -> None:
        self.row = row
        self.rows = rows

    async def execute(self, _stmt: object) -> object:
        return self.rows if self.rows is not None else _Result(self.row)


class _NoDB:
    async def execute(self, _stmt: object) -> object:
        raise AssertionError("запрос к БД здесь не ожидался")


@pytest.mark.parametrize(
    ("status", "kind", "claim", "expected"),
    [
        ("active", "person", None, True),
        ("active", "person", "person", True),
        ("active", "service", None, False),
        # Вид берём с карточки: claim «person» кассу человеком не делает.
        ("active", "service", "person", False),
        # Claim умеет только запретить: синк не дошёл, а токен уже «service».
        ("active", "person", "service", False),
        ("archived", "person", None, False),
        # Несохранённый объект и незнакомый вид — отказ при сомнении.
        ("active", None, None, False),
        ("active", "kiosk", None, False),
    ],
)
def test_rule_matrix(status, kind, claim, expected):
    card = _card(status=status, account_kind=kind)
    assert card_grants_rights(card, _p(account_kind=claim)) is expected


def test_no_profile_and_principal_without_claim_attribute():
    assert card_grants_rights(None) is False
    # Старая либа: атрибута нет вовсе — решает карточка.
    assert card_grants_rights(_card(), SimpleNamespace()) is True
    assert card_grants_rights(_card(account_kind="service"), SimpleNamespace()) is False


def test_effective_roles_mask_only_what_grants_rights():
    office = _card(org_role="office", content_role="publisher")
    assert effective_org_role(office) == "office"
    assert effective_content_role(office) == "publisher"
    kiosk = _card(org_role="office", content_role="publisher", account_kind="service")
    assert effective_org_role(kiosk) == "employee"
    assert effective_content_role(kiosk) == "none"
    archived = _card(org_role="tu", content_role="author", status="archived")
    assert effective_org_role(archived) == "employee"
    assert effective_content_role(archived) == "none"
    assert effective_org_role(None) == "employee"
    assert effective_content_role(None) == "none"
    # Данные карточки маска не трогает.
    assert kiosk.org_role == "office"


async def test_scope_of_kiosk_is_self_before_any_store_query(monkeypatch):
    kiosk = _card(org_role="tu", account_kind="service")

    async def _get_profile(_db, _principal):
        return kiosk

    monkeypatch.setattr(org_scope, "get_profile", _get_profile)
    scope = await org_scope.resolve_scope(_NoDB(), _p())
    # profile_id остаётся: своя карточка кассе видна, как и сегодня.
    assert scope == org_scope.Scope(kind="self", profile_id=kiosk.id)


async def test_scope_claim_service_denies_and_person_keeps_stores(monkeypatch):
    tu = _card(org_role="tu")
    store_id = uuid.uuid4()

    async def _get_profile(_db, _principal):
        return tu

    monkeypatch.setattr(org_scope, "get_profile", _get_profile)
    denied = await org_scope.resolve_scope(_NoDB(), _p(account_kind="service"))
    assert denied == org_scope.Scope(kind="self", profile_id=tu.id)
    allowed = await org_scope.resolve_scope(_DB(rows=[(store_id,)]), _p())
    assert allowed.kind == "stores"
    assert allowed.store_ids == frozenset({store_id})


def _patch_report_gate(monkeypatch, profile, content_role: str = "none") -> None:
    async def _role(_db, _principal):
        return content_role

    async def _get_profile(_db, _principal):
        return profile

    monkeypatch.setattr(reports, "resolve_content_role", _role)
    monkeypatch.setattr(reports, "get_profile", _get_profile)


@pytest.mark.parametrize("org_role", ["office", "tu", "franchisee_owner"])
async def test_kiosk_with_contour_gets_no_reports(monkeypatch, org_role):
    _patch_report_gate(monkeypatch, _card(org_role=org_role, account_kind="service"))
    with pytest.raises(HTTPException) as exc:
        await reports._require_report_access(_NoDB(), _p())
    assert exc.value.status_code == 403
    assert exc.value.detail == reports.KIOSK_REPORTS_DENIED


async def test_person_contour_still_opens_reports(monkeypatch):
    _patch_report_gate(monkeypatch, _card(org_role="office"))
    assert await reports._require_report_access(_NoDB(), _p()) == "full"
    _patch_report_gate(monkeypatch, _card(org_role="franchisee_owner"))
    assert await reports._require_report_access(_NoDB(), _p()) == "franchisee"
    _patch_report_gate(monkeypatch, _card(org_role="office"))
    with pytest.raises(HTTPException) as exc:
        await reports._require_report_access(_NoDB(), _p(account_kind="service"))
    assert exc.value.status_code == 403
    # Без карточки — прежний общий текст.
    _patch_report_gate(monkeypatch, None)
    with pytest.raises(HTTPException) as exc:
        await reports._require_report_access(_NoDB(), _p())
    assert exc.value.detail != reports.KIOSK_REPORTS_DENIED


async def test_can_create_project_needs_person_card():
    row = SimpleNamespace(org_role="office", status="active", account_kind="service")
    assert await project_access.can_create_project(_DB(row=row), _p()) is False
    row = SimpleNamespace(org_role="office", status="active", account_kind="person")
    assert await project_access.can_create_project(_DB(row=row), _p()) is True
    assert (
        await project_access.can_create_project(_DB(row=row), _p(account_kind="service"))
        is False
    )
    archived = SimpleNamespace(org_role="office", status="archived", account_kind="person")
    assert await project_access.can_create_project(_DB(row=archived), _p()) is False
    assert await project_access.can_create_project(_DB(row=None), _p()) is False
    assert await project_access.can_create_project(_NoDB(), _p("admin")) is True
    assert await project_access.can_create_project(_NoDB(), _p("viewer")) is False


async def test_content_role_needs_person_card():
    def row(**kw: str) -> SimpleNamespace:
        return SimpleNamespace(**{"content_role": "publisher", "status": "active",
                                  "account_kind": "person", **kw})

    resolve = content_access.resolve_content_role
    assert await resolve(_DB(row=row()), _p()) == "publisher"
    assert await resolve(_DB(row=row(account_kind="service")), _p()) == "none"
    assert await resolve(_DB(row=row()), _p(account_kind="service")) == "none"
    assert await resolve(_DB(row=row(status="archived")), _p()) == "none"
    assert await resolve(_DB(row=row(content_role="author")), _p()) == "author"
    assert await resolve(_DB(row=None), _p()) == "none"
    assert await resolve(_NoDB(), _p("admin")) == "admin"


def test_access_grant_fields_names_what_lies_on_the_card():
    full = _card(org_role="tu", franchisee_id=uuid.uuid4(), content_role="publisher")
    assert access_grant_fields(full, 2) == [
        "org_role",
        "franchisee_id",
        "tu_stores",
        "content_role",
    ]
    assert access_grant_fields(_card(), 0) == []

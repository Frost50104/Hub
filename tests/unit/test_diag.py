"""POST /api/diag — диагностика обновления с устройства (25.09).

Схема — зеркало `web/src/lib/swDiag.ts`; ручка пишет тело в журнал строкой
`client_diag`. Проверяем то, что нашло adversarial-ревью плана: поле `kind`
(не `event`), вложенное тело в логе, `extra="forbid"`, потолки длины и
ответ 204 с рейт-лимитом.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError
from structlog.testing import capture_logs

from app.api import diag as diag_api
from app.schemas.diag import SwDiagIn


def _body(kind: str = "update_click", **over: object) -> dict:
    body = {
        "kind": kind,
        "ts": "2026-09-25T07:41:13.000Z",
        "app": {
            "loaded": "aaaaaaa-20260925-100000",
            "server": "bbbbbbb-20260925-110000",
            "mode": "production",
        },
        "env": {
            "ua": "Mozilla/5.0 (Macintosh) Safari",
            "standalone": False,
            "online": True,
            "visible": True,
            "path": "/my",
            "page_age_ms": 12345,
        },
        "sw": {
            "supported": True,
            "controlled": True,
            "active": True,
            "waiting": False,
            "installing": True,
            "health": "hung",
            "probe_age_ms": 25000,
            "hung_after_ms": 7345,
            "lookup_timed_out": False,
        },
    }
    if kind == "update_click":
        body["click"] = {
            "action": "reload",
            "total_ms": 1235,
            "steps": [
                {"name": "lookup", "ms": 12, "result": "ok"},
                {"name": "version", "ms": 80, "result": "ok"},
                {"name": "inflight", "ms": 0, "result": "skipped"},
            ],
        }
    body.update(over)
    return body


def test_schema_accepts_both_kinds() -> None:
    click = SwDiagIn.model_validate(_body("update_click"))
    assert click.kind == "update_click"
    assert click.click is not None
    assert click.click.steps[0].name == "lookup"
    hung = SwDiagIn.model_validate(_body("sw_hung"))
    assert hung.click is None
    assert SwDiagIn.model_validate(_body("sw_recovered")).kind == "sw_recovered"


def test_schema_rejects_event_and_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        SwDiagIn.model_validate(_body(event="sw_hung"))
    with pytest.raises(ValidationError):
        SwDiagIn.model_validate(_body(kind="something_else"))
    with pytest.raises(ValidationError):
        body = _body()
        body["env"]["ua"] = "x" * 201
        SwDiagIn.model_validate(body)
    with pytest.raises(ValidationError):
        body = _body()
        body["click"]["steps"] = [{"name": "lookup", "ms": 1, "result": "ok"}] * 13
        SwDiagIn.model_validate(body)


async def test_handler_logs_nested_body_and_returns_204(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []

    async def no_rate_limit(**kwargs: object) -> None:
        calls.append(dict(kwargs))

    monkeypatch.setattr(diag_api, "enforce_rate_limit", no_rate_limit)
    principal = SimpleNamespace(employee_id=uuid4(), tenant_id=uuid4())
    body = SwDiagIn.model_validate(_body("sw_hung"))

    with capture_logs() as logs:
        response = await diag_api.post_diag(body, principal)  # type: ignore[arg-type]

    assert response.status_code == 204
    assert calls == [
        {
            "bucket": "diag:send",
            "employee_id": str(principal.employee_id),
            "limit": diag_api.DIAG_RATE_LIMIT,
            "window_sec": diag_api.DIAG_RATE_WINDOW_SEC,
        }
    ]
    entry = next(e for e in logs if e["event"] == "client_diag")
    assert entry["kind"] == "sw_hung"
    assert entry["diag"]["sw"]["health"] == "hung"
    assert entry["diag"]["kind"] == "sw_hung"


class _FakePipeline:
    """Ровно то, чем пользуется `check_and_increment`: incr + expire + execute."""

    def __init__(self, store: dict[str, int]) -> None:
        self.store = store
        self.ops: list[tuple] = []

    def incr(self, key: str) -> _FakePipeline:
        self.ops.append(("incr", key))
        return self

    def expire(self, key: str, ttl: int) -> _FakePipeline:
        self.ops.append(("expire", key, ttl))
        return self

    async def execute(self) -> list:
        out: list = []
        for op in self.ops:
            if op[0] == "incr":
                self.store[op[1]] = self.store.get(op[1], 0) + 1
                out.append(self.store[op[1]])
            else:
                out.append(True)
        return out


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, int] = {}

    def pipeline(self) -> _FakePipeline:
        return _FakePipeline(self.store)


async def test_handler_returns_429_after_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Живой лимит 30/час: 31-й вызов — 429 с Retry-After. Redis — в памяти:
    настоящего в тестовом окружении нет, а остальные тесты лимитер выключают."""
    from fastapi import HTTPException

    from app import deps

    fake = _FakeRedis()
    monkeypatch.setattr(deps, "get_redis", lambda: fake)
    principal = SimpleNamespace(employee_id=uuid4(), tenant_id=uuid4())
    body = SwDiagIn.model_validate(_body("update_click"))

    for _ in range(diag_api.DIAG_RATE_LIMIT):
        response = await diag_api.post_diag(body, principal)  # type: ignore[arg-type]
        assert response.status_code == 204

    with pytest.raises(HTTPException) as exc:
        await diag_api.post_diag(body, principal)  # type: ignore[arg-type]
    assert exc.value.status_code == 429
    assert exc.value.headers is not None
    assert exc.value.headers["Retry-After"] == str(diag_api.DIAG_RATE_WINDOW_SEC)
    assert fake.store == {f"rl:diag:send:{principal.employee_id}": diag_api.DIAG_RATE_LIMIT + 1}

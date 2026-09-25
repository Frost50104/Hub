"""Код рубильника в теле 404 от auth — обе формы и любое тело без падения.

Фактическая форма auth — `{"detail": {"code": …}}` (FastAPI оборачивает
`detail`); `sites_sync` до правки читал только плоское `{"code": …}` и слал
выключенный реестр в журнал WARNING'ом как «голый 404».
"""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from structlog.testing import capture_logs

from app.services import sites_sync
from app.services.auth_http import disabled_code


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"json": {"detail": {"code": "hr_export_disabled"}}}, "hr_export_disabled"),
        ({"json": {"code": "sites_export_disabled"}}, "sites_export_disabled"),
        ({"json": {"detail": "Not Found"}}, None),
        ({"json": {"detail": {"code": ""}}}, None),
        ({"json": {"detail": {"code": 404}}}, None),
        ({"json": ["sites_export_disabled"]}, None),
        ({"text": "<html>nope</html>"}, None),
        ({}, None),
    ],
)
def test_disabled_code(kwargs, expected):
    assert disabled_code(httpx.Response(404, **kwargs)) == expected


_REAL_ASYNC_CLIENT = httpx.AsyncClient


def _mock_sites_transport(monkeypatch, response: httpx.Response) -> None:
    def make_client(**kw):
        kw.pop("timeout", None)
        return _REAL_ASYNC_CLIENT(transport=httpx.MockTransport(lambda r: response), **kw)

    monkeypatch.setattr(sites_sync.httpx, "AsyncClient", make_client)
    monkeypatch.setattr(
        sites_sync,
        "get_settings",
        lambda: SimpleNamespace(
            staff_service_key="svc_test", signaris_auth_base_url="https://auth.test"
        ),
    )


async def test_sites_disabled_in_detail_is_quiet(monkeypatch):
    _mock_sites_transport(
        monkeypatch, httpx.Response(404, json={"detail": {"code": "sites_export_disabled"}})
    )
    with capture_logs() as logs:
        assert await sites_sync._fetch_sites() is None
    assert [e["log_level"] for e in logs] == ["info"]
    assert logs[0]["event"] == "sites_sync.unavailable"


async def test_sites_bare_404_warns_with_url(monkeypatch):
    _mock_sites_transport(monkeypatch, httpx.Response(404, json={"detail": "Not Found"}))
    with capture_logs() as logs:
        assert await sites_sync._fetch_sites() is None
    assert [e["log_level"] for e in logs] == ["warning"]
    assert logs[0]["url"].startswith("https://auth.test/api/products/sites")

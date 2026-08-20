"""Async-клиент iikoServer OLAP (волна 2 ассистента).

Порт проверенного `Listen/recorder/olap/iiko_source.py` на httpx.AsyncClient.
Что перенесено дословно и менять нельзя:

- **Каждое подключение занимает слот лицензии iiko** → `logout` вызывается в
  `finally` при любом исходе. Это условие эксплуатации, а не аккуратность:
  сеть кофеен делит фиксированное число слотов, и «забытая» сессия выводит
  из строя не наш отчёт, а чужую кассу.
- auth: `GET /resto/api/auth?login=&pass=sha1hex(password)` → токен строкой.
- OLAP v2: `POST /resto/api/v2/reports/olap?key=` → `{"data": [ {...} ]}`.
- Фильтр периода `OpenDate.Typed`, `to` **ЭКСКЛЮЗИВНА** и должна быть > `from`.
- Время в ответах — наивное локальное MSK, НЕ UTC (проверено в Listen 03.06:
  конвертация −3ч уводила данные на три часа назад).

Транспорт инъектируется — тесты гоняют весь разбор через httpx.MockTransport
без живого сервера.
"""

from __future__ import annotations

import hashlib
from datetime import date, timedelta
from types import TracebackType
from typing import Any

import httpx
import structlog

log = structlog.get_logger("iiko.client")


class IikoError(RuntimeError):
    """Сеть/авторизация/формат — API мапит в 502."""


class IikoNotConfigured(RuntimeError):
    """Нет хоста или кредов — API мапит в 503 («не подключён»)."""


class IikoAuthError(IikoError):
    """Неверный логин/пароль. Отдельный класс: лечится сменой .env, а не
    повтором запроса, и сообщение сотруднику должно это отражать."""


class IikoClient:
    """Одна сессия к iikoServer. Использовать ТОЛЬКО как async-контекст."""

    def __init__(
        self,
        *,
        base_url: str,
        login: str,
        password: str,
        verify_ssl: bool = True,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._login = login
        self._password = password
        self._token: str | None = None
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            verify=verify_ssl,
            timeout=timeout,
            transport=transport,
        )

    async def __aenter__(self) -> IikoClient:
        await self.login()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.logout()
        await self._client.aclose()

    async def login(self) -> None:
        pw = hashlib.sha1(self._password.encode("utf-8")).hexdigest()  # noqa: S324 — требование iiko
        try:
            r = await self._client.get(
                "/resto/api/auth", params={"login": self._login, "pass": pw}
            )
        except httpx.HTTPError as e:
            raise IikoError(f"iiko недоступен: {e}") from None
        if r.status_code == 401:
            raise IikoAuthError(
                "iiko отклонил логин или пароль — обновите SIGNARIS_HUB_IIKO_LOGIN/PASSWORD"
            )
        if r.status_code != 200:
            raise IikoError(f"iiko auth {r.status_code}: {r.text[:200]}")
        self._token = r.text.strip().strip('"')

    async def logout(self) -> None:
        """Освободить слот лицензии. Ошибку глушим намеренно: не смогли
        разлогиниться — это не повод уронить уже собранный отчёт, слот
        освободится по таймауту сессии."""
        if not self._token:
            return
        try:
            await self._client.get("/resto/api/logout", params={"key": self._token})
        except httpx.HTTPError as e:
            log.warning("iiko.logout_failed", error=str(e))
        finally:
            self._token = None

    def _require_token(self) -> str:
        if not self._token:
            raise IikoError("Нет сессии iiko: используйте async with IikoClient(...)")
        return self._token

    async def columns(self, report_type: str) -> dict[str, Any]:
        """Доступные поля OLAP. Нужны, чтобы пресет падал внятной ошибкой
        «поле X недоступно», а не пустым отчётом."""
        r = await self._client.get(
            "/resto/api/v2/reports/olap/columns",
            params={"key": self._require_token(), "reportType": report_type},
        )
        if r.status_code != 200:
            raise IikoError(f"iiko columns {r.status_code}: {r.text[:200]}")
        return r.json()

    async def olap(
        self,
        *,
        report_type: str,
        date_from: date,
        date_to: date,
        group_by: list[str],
        aggregate: list[str],
        date_field: str = "OpenDate.Typed",
        extra_filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """OLAP-выгрузка за [date_from, date_to] ВКЛЮЧИТЕЛЬНО.

        Наружу отдаём человеческий полуинтервал, внутрь — эксклюзивный `to`
        iiko (+1 день). Это единственное место, где живёт это правило:
        «отчёт за 18 августа» с `to=18` вернул бы пусто, а пустой ответ на
        экране неотличим от «продаж не было».
        """
        if date_to < date_from:
            raise IikoError("Конец периода раньше начала")
        filters: dict[str, Any] = {
            date_field: {
                "filterType": "DateRange",
                "periodType": "CUSTOM",
                "from": date_from.isoformat(),
                "to": (date_to + timedelta(days=1)).isoformat(),
            }
        }
        filters.update(extra_filters or {})
        body = {
            "reportType": report_type,
            "buildSummary": False,
            "groupByRowFields": group_by,
            "aggregateFields": aggregate,
            "filters": filters,
        }
        try:
            r = await self._client.post(
                "/resto/api/v2/reports/olap",
                params={"key": self._require_token()},
                json=body,
            )
        except httpx.HTTPError as e:
            raise IikoError(f"iiko не ответил: {e}") from None
        if r.status_code != 200:
            raise IikoError(f"iiko olap {r.status_code}: {r.text[:200]}")
        try:
            data = r.json().get("data", [])
        except ValueError:
            raise IikoError("iiko вернул не JSON") from None
        if not isinstance(data, list):
            raise IikoError("iiko вернул неожиданную структуру ответа")
        return data

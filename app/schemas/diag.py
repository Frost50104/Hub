"""Диагностика обновления с устройства — тело `POST /api/diag`.

Зеркало `web/src/lib/swDiag.ts::SwDiagPayload`, меняется ПАРОЙ. Верхнее поле
называется `kind`, а не `event`: у structlog первый позиционный аргумент
`log.info("client_diag", …)` и есть `event`, распаковка тела с таким ключом
роняла бы ручку в 500. `extra="forbid"` — как у остальных тел: лишний ключ
значит расхождение с фронтом, и лучше 422 в журнале, чем молча потерянное поле.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Потолок тела на фронте — 2 КБ (`keepalive`-запросы делят 64 КБ на всё);
# лимиты полей здесь держат ту же величину.
UA_MAX = 200
PATH_MAX = 200
VERSION_MAX = 80
STEPS_MAX = 12


class DiagApp(BaseModel):
    model_config = ConfigDict(extra="forbid")

    loaded: str = Field(max_length=VERSION_MAX)
    server: str | None = Field(default=None, max_length=VERSION_MAX)
    mode: str = Field(max_length=32)


class DiagEnv(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ua: str = Field(max_length=UA_MAX)
    standalone: bool
    online: bool
    visible: bool
    path: str = Field(max_length=PATH_MAX)
    page_age_ms: int = Field(ge=0)


class DiagSw(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supported: bool
    controlled: bool
    active: bool
    waiting: bool
    installing: bool
    health: Literal["unknown", "ok", "hung"]
    probe_age_ms: int | None = Field(default=None, ge=0)
    hung_after_ms: int | None = Field(default=None, ge=0)
    lookup_timed_out: bool


class DiagStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Literal["lookup", "version", "token", "inflight", "activate", "purge"]
    ms: int = Field(ge=0)
    result: Literal["ok", "timeout", "error", "skipped"]


class DiagClick(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str = Field(max_length=40)
    total_ms: int = Field(ge=0)
    steps: list[DiagStep] = Field(max_length=STEPS_MAX)


class SwDiagIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["sw_hung", "update_click"]
    ts: str = Field(max_length=40)
    app: DiagApp
    env: DiagEnv
    sw: DiagSw
    click: DiagClick | None = None

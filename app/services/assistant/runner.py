"""Цикл витков с инструментами.

Инвариант: **write-инструмент, требующий подтверждения, обрывает цикл.**
Модель не получает следующего витка и не может «дорисовать» результат,
которого ещё нет — карточка плана уходит человеку такой, какой её собрал
сервер. Немедленные правки (одна задача) возвращаются модели, чтобы она
сформулировала ответ.

Бюджеты подобраны под nginx: локация `/api/ai/` держит 120 с, внутренний
потолок 40 с. Лучше честная ошибка в журнале, чем 504 от прокси, после
которого сотрудник не знает, применилось действие или нет.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

import structlog
from pydantic import ValidationError

from app.services.assistant.context import Ambiguous, NotFound, ToolContext
from app.services.assistant.prompts import system_prompt
from app.services.assistant.tools import TOOLS, Tool
from app.services.llm import ChatMessage, LLMError, ToolSpec

log = structlog.get_logger("assistant.runner")

MAX_ITERATIONS = 4
TIME_BUDGET_SEC = 40.0
# Результат инструмента, уехавший в модель, обрезается: двадцать задач с
# описаниями раздули бы контекст до денег и до таймаута.
MAX_TOOL_RESULT_CHARS = 12_000


@dataclass
class Turn:
    """Оборот журнала — то, что увидит сотрудник."""

    kind: str  # answer | summary | action | denied | error
    content: str
    sources: list[dict[str, Any]] = field(default_factory=list)
    data: dict[str, Any] | None = None
    # Заполняется, когда инструмент предложил план (kind == "action").
    plan: dict[str, Any] | None = None


def tool_specs() -> list[ToolSpec]:
    """JSON Schema аргументов выводится из pydantic-моделей — второго
    описания контракта не существует, разъехаться нечему."""
    specs: list[ToolSpec] = []
    for tool in TOOLS:
        schema = tool.args_model.model_json_schema()
        schema.pop("title", None)
        specs.append(ToolSpec(name=tool.name, description=tool.description, parameters=schema))
    return specs


async def _run_tool(ctx: ToolContext, tool: Tool, raw_args: dict[str, Any]) -> dict[str, Any]:
    """Выполнить инструмент, превратив любые сбои в ДАННЫЕ для модели.

    Исключение здесь означало бы 500 на всю ручку из-за того, что модель
    ошиблась в имени сотрудника, — вместо этого она получает описание
    проблемы и может переспросить.
    """
    try:
        args = tool.args_model.model_validate(raw_args)
    except ValidationError as e:
        return {"error": "Неверные аргументы", "details": e.errors(include_url=False)[:3]}
    try:
        return await tool.handler(ctx, args)
    except Ambiguous as e:
        return {"ambiguous": True, "what": e.what, "candidates": e.candidates}
    except NotFound as e:
        return {"error": str(e)}


def _extract_bullets(text: str) -> list[str]:
    lines = [ln.strip() for ln in text.splitlines()]
    return [
        ln.lstrip("-*• ").strip()
        for ln in lines
        if ln.startswith(("- ", "* ", "• "))
    ]


async def run(
    ctx: ToolContext,
    *,
    provider: Any,
    question: str,
    history: list[ChatMessage],
) -> Turn:
    started = time.monotonic()
    specs = tool_specs()
    messages: list[ChatMessage] = [
        ChatMessage(role="system", content=system_prompt()),
        *history,
        ChatMessage(role="user", content=question),
    ]
    sources: list[dict[str, Any]] = []
    denied_payload: dict[str, Any] | None = None
    used_summary_tool = False

    for _ in range(MAX_ITERATIONS):
        if time.monotonic() - started > TIME_BUDGET_SEC:
            return Turn(
                kind="error",
                content="Не успел собрать ответ за отведённое время. "
                "Попробуйте спросить конкретнее — например, назвать проект.",
            )
        result = await provider.chat_with_tools(messages, specs)
        if not result.tool_calls:
            content = result.content.strip()
            if denied_payload is not None:
                return Turn(kind="denied", content=content, data=denied_payload)
            bullets = _extract_bullets(content)
            if used_summary_tool and len(bullets) >= 3:
                return Turn(kind="summary", content=content, data={"lines": bullets})
            return Turn(kind="answer", content=content, sources=sources)

        messages.append(
            ChatMessage(role="assistant", content=result.content, tool_calls=result.tool_calls)
        )
        for call in result.tool_calls:
            tool = next((t for t in TOOLS if t.name == call.name), None)
            if tool is None:
                payload: dict[str, Any] = {"error": f"Нет инструмента {call.name}"}
            else:
                payload = await _run_tool(ctx, tool, call.arguments)

            if "__plan__" in payload:
                # Обрыв цикла: дальше решает человек.
                return Turn(kind="action", content="", plan=payload["__plan__"])
            if payload.get("denied"):
                denied_payload = {
                    "reason": payload.get("reason", ""),
                    "who_can": payload.get("who_can", []),
                }
            if call.name == "search_knowledge":
                sources = [
                    {"title": d["title"], "url_path": d["url"]}
                    for d in payload.get("documents", [])
                ]
            if call.name in ("project_summary", "my_tasks", "search_tasks"):
                used_summary_tool = True

            messages.append(
                ChatMessage(
                    role="tool",
                    tool_call_id=call.id,
                    content=json.dumps(payload, ensure_ascii=False, default=str)[
                        :MAX_TOOL_RESULT_CHARS
                    ],
                )
            )

    # Витки исчерпаны — просим модель ответить БЕЗ инструментов, иначе
    # сотрудник получит пустоту после четырёх обращений к провайдеру.
    try:
        nudge = ChatMessage(
            role="user",
            content="Ответь по уже собранным данным, без вызова инструментов.",
        )
        final = await provider.chat([*messages, nudge])
    except LLMError:
        log.warning("assistant.iterations_exhausted")
        return Turn(
            kind="error",
            content="Запрос оказался слишком сложным — разбейте его на два.",
        )
    return Turn(kind="answer", content=final.strip(), sources=sources)

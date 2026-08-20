"""Ассистент Hub: журнал операций, инструменты трекера, планы действий.

Наследник `/api/learn/ai/*` (Ф6). Отличия, из-за которых заведён отдельный
модуль, а не расширен старый:

- диалог принадлежит СОТРУДНИКУ, а не учебному профилю (иначе пользователь
  без learn-профиля получал 404 «Профиль не найден»);
- ответ — оборот журнала (`kind` + `data`), а не реплика чата;
- есть действия, и всё, что создаёт или архивирует, проходит через план.

Старые пути остаются алиасами в `app/api/ai.py`: PWA с
`registerType:'prompt'` живёт вчерашним бандлом ещё несколько дней после
деплоя.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from signaris_auth import Principal
from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.deps import enforce_rate_limit, get_db, require_auth
from app.models.ai import AiConversation, AiMessage, AiPlan
from app.services.assistant import plans as plan_service
from app.services.assistant.context import ToolContext
from app.services.assistant.runner import Turn, run
from app.services.llm import (
    ChatMessage,
    LLMError,
    LLMNotConfigured,
    LLMToolsUnsupported,
    get_provider,
)
from app.services.org_scope import get_profile
from app.services.stt import STTError, STTNotConfigured, get_stt

router = APIRouter(tags=["assistant"])
log = structlog.get_logger("assistant.api")

HISTORY_LIMIT = 8

# Вопрос и ответ одного оборота пишутся В ОДНОЙ транзакции, а `now()` в
# Postgres — время НАЧАЛА транзакции: `created_at` у них совпадает до
# микросекунды, и сортировка только по нему неустойчива (журнал мог
# показать ответ выше вопроса). Внутри оборота порядок задаёт роль.
_ROLE_RANK = case((AiMessage.role == "user", 0), else_=1)


class AskBody(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    conversation_id: UUID | None = None


class TurnResponse(BaseModel):
    conversation_id: UUID
    message_id: UUID
    kind: str
    content: str
    sources: list[dict[str, Any]] = []
    data: dict[str, Any] | None = None


class MessageResponse(BaseModel):
    id: UUID
    role: str
    kind: str
    content: str
    sources: list[dict[str, Any]] | None
    data: dict[str, Any] | None
    created_at: str


class ConversationResponse(BaseModel):
    id: UUID
    title: str
    updated_at: str


class StatusResponse(BaseModel):
    configured: bool
    provider: str | None = None
    # Провайдер без function-calling: ассистент отвечает, но не действует.
    can_act: bool = False
    # Голосовой ввод настроен. Неактивный микрофон выглядит как сломанный,
    # поэтому кнопки просто нет, пока STT не подключён.
    voice: bool = False


async def _hydrate(db: AsyncSession, data: dict[str, Any] | None) -> dict[str, Any] | None:
    """Подставить ЖИВОЙ план вместо ссылки на него.

    Единственный источник истины о состоянии действия — таблица `ai_plans`.
    Журнал хранит только id, иначе после «Выполнить» карточка вечно
    показывала бы «проверьте перед выполнением».
    """
    if not data:
        return data
    # `plan_id` — текущая форма. `plan.id` — форма первых staging-строк, где
    # план сохранялся снимком; читаем и её, иначе уже заведённые диалоги
    # остались бы с мёртвой карточкой после деплоя.
    plan_id = data.get("plan_id") or (data.get("plan") or {}).get("id")
    if plan_id is None:
        return data
    rest = {k: v for k, v in data.items() if k not in ("plan_id", "plan")}
    plan = await db.get(AiPlan, UUID(str(plan_id)))
    if plan is None:
        return rest
    return {**rest, "plan": plan_service.serialize(plan)}


async def _ctx(db: AsyncSession, principal: Principal) -> ToolContext:
    return ToolContext(db=db, principal=principal, profile=await get_profile(db, principal))


@router.get("/ai/status", response_model=StatusResponse)
async def status(_principal: Principal = Depends(require_auth())) -> StatusResponse:
    try:
        provider = get_provider()
    except LLMNotConfigured:
        return StatusResponse(configured=False, voice=get_settings().stt_enabled)
    return StatusResponse(
        configured=True,
        provider=provider.name,
        can_act=getattr(provider, "supports_tools", False),
        voice=get_settings().stt_enabled,
    )


async def _load_conversation(
    db: AsyncSession, principal: Principal, conversation_id: UUID | None, *, title: str
) -> AiConversation:
    if conversation_id is not None:
        found = await db.get(AiConversation, conversation_id)
        if found is None or found.employee_id != principal.employee_id:
            raise HTTPException(status_code=404, detail="Диалог не найден")
        return found
    profile = await get_profile(db, principal)
    fresh = AiConversation(
        tenant_id=principal.tenant_id,
        employee_id=principal.employee_id,
        profile_id=profile.id if profile else None,
        title=title[:80],
    )
    db.add(fresh)
    await db.flush()
    return fresh


async def _action_trace(db: AsyncSession, message: AiMessage) -> str:
    """След оборота-действия в истории МОДЕЛИ.

    Регресс staging 20.08: карточка плана рисуется без прозы, поэтому
    ассистентское сообщение уходило в БД с пустым `content` — и в истории
    просьба «создай задачу» выглядела неотвеченной. На следующий вопрос
    (совсем про другое) модель добросовестно предлагала создать ту же задачу
    заново. Пустых ответов в истории быть не должно: если на экране блок, а
    не текст, модель обязана получить его пересказ.
    """
    data = await _hydrate(db, message.data)
    plan = (data or {}).get("plan")
    if not plan:
        if message.kind == "denied":
            return f"[Действие отклонено правами: {(data or {}).get('reason', '')}]"
        return ""
    what = plan.get("scope") or plan.get("tool", "действие")
    if plan.get("status") == "done":
        return f"[Действие выполнено: {what}. {(plan.get('result') or {}).get('text', '')}]"
    if plan.get("status") == "rejected":
        return f"[Сотрудник отклонил план: {what}]"
    if plan.get("status") == "failed":
        return f"[Действие не выполнено: {what}. {plan.get('error') or ''}]"
    return (
        f"[Показан план ({what}), ждёт подтверждения сотрудника. "
        "Повторно предлагать то же действие не нужно.]"
    )


async def _history(db: AsyncSession, conversation_id: UUID) -> list[ChatMessage]:
    """Последние обороты для контекста модели.

    Блоки не пересказываются дословно (план и отчёт — состояние UI), но их
    ИТОГ в историю попадает обязательно — см. `_action_trace`.
    """
    rows = (
        (
            await db.execute(
                select(AiMessage)
                .where(AiMessage.conversation_id == conversation_id)
                .order_by(AiMessage.created_at.desc(), _ROLE_RANK.desc())
                .limit(HISTORY_LIMIT)
            )
        )
        .scalars()
        .all()
    )
    out: list[ChatMessage] = []
    for m in reversed(rows):
        text = m.content.strip()
        if not text and m.role == "assistant":
            text = await _action_trace(db, m)
        if text:
            out.append(ChatMessage(role=m.role, content=text))
    return out


@router.post("/ai/ask", response_model=TurnResponse)
async def ask(
    body: AskBody,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> TurnResponse:
    await enforce_rate_limit(
        bucket="ai:ask", employee_id=str(principal.employee_id), limit=20, window_sec=60
    )
    try:
        provider = get_provider()
    except LLMNotConfigured as e:
        raise HTTPException(status_code=503, detail=str(e)) from None

    conversation = await _load_conversation(
        db, principal, body.conversation_id, title=body.question
    )
    history = await _history(db, conversation.id)
    ctx = await _ctx(db, principal)

    try:
        turn = await run(ctx, provider=provider, question=body.question, history=history)
    except LLMToolsUnsupported:
        # Деградация, а не отказ: провайдер без инструментов всё ещё умеет
        # отвечать по базе знаний.
        turn = await _fallback_answer(ctx, provider, body.question, history)
    except LLMError as e:
        log.warning("assistant.provider_error", error=str(e))
        turn = Turn(
            kind="error",
            content="AI-провайдер не ответил. Ничего не изменено — попробуйте ещё раз.",
        )

    db.add(
        AiMessage(
            tenant_id=principal.tenant_id,
            conversation_id=conversation.id,
            role="user",
            kind="answer",
            content=body.question,
        )
    )
    data = turn.data
    if turn.plan is not None:
        plan = plan_service.create(
            db,
            tenant_id=principal.tenant_id,
            conversation_id=conversation.id,
            employee_id=principal.employee_id,
            proposal=turn.plan,
        )
        await db.flush()
        # В сообщение кладём ССЫЛКУ, а не снимок плана: снимок навсегда
        # остался бы «pending», и карточка после «Выполнить» показывала бы
        # кнопки заново при каждом открытии диалога.
        data = {"plan_id": str(plan.id)}

    message = AiMessage(
        tenant_id=principal.tenant_id,
        conversation_id=conversation.id,
        role="assistant",
        kind=turn.kind,
        content=turn.content,
        sources=turn.sources or None,
        data=data,
    )
    db.add(message)
    await db.flush()
    if turn.plan is not None:
        plan.message_id = message.id
    await db.commit()
    return TurnResponse(
        conversation_id=conversation.id,
        message_id=message.id,
        kind=turn.kind,
        content=turn.content,
        sources=turn.sources,
        data=await _hydrate(db, data),
    )


async def _fallback_answer(
    ctx: ToolContext, provider: Any, question: str, history: list[ChatMessage]
) -> Turn:
    """Ответ без инструментов — только база знаний (поведение Ф6)."""
    from app.services.assistant.tools import KnowledgeArgs, t_search_knowledge

    found = await t_search_knowledge(ctx, KnowledgeArgs(query=question))
    docs = found.get("documents", [])
    context = "\n\n".join(
        f"[{i + 1}] {d['title']}\n{d['text']}" for i, d in enumerate(docs)
    ) or "(база знаний пуста)"
    answer = await provider.chat(
        [
            ChatMessage(
                role="system",
                content=(
                    "Ты — помощник по базе знаний компании. Отвечай ТОЛЬКО по "
                    "контексту ниже, ссылайся на источники [1], [2]. Не выдумывай.\n\n"
                    f"КОНТЕКСТ:\n{context}"
                ),
            ),
            *history,
            ChatMessage(role="user", content=question),
        ]
    )
    return Turn(
        kind="answer",
        content=answer.strip(),
        sources=[{"title": d["title"], "url_path": d["url"]} for d in docs],
    )


# ─── Голосовой ввод ─────────────────────────────────────────────────────────


class TranscriptResponse(BaseModel):
    text: str


@router.post("/ai/transcribe", response_model=TranscriptResponse)
async def transcribe(
    request: Request,
    principal: Principal = Depends(require_auth()),
) -> TranscriptResponse:
    """Запись из браузера → текст В ПОЛЕ ВВОДА.

    Расшифровка НЕ отправляется как команда: голос не должен запускать
    действие мимо глаз — сотрудник читает и правит текст, отправка остаётся
    отдельной кнопкой (спека макета).

    При `stt_provider=local` считает отдельный юнит на 127.0.0.1: веса модели
    не должны жить в API-процессе (см. `app/stt_service.py`).
    """
    settings = get_settings()
    if not settings.stt_enabled:
        raise HTTPException(
            status_code=503, detail="Голосовой ввод не подключён"
        )
    await enforce_rate_limit(
        bucket="ai:stt", employee_id=str(principal.employee_id), limit=20, window_sec=60
    )
    audio = await request.body()
    if not audio:
        raise HTTPException(status_code=422, detail="Пустая запись")
    if len(audio) > settings.stt_max_bytes:
        raise HTTPException(
            status_code=413,
            detail="Запись слишком длинная — скажите короче",
        )
    content_type = request.headers.get("content-type", "application/octet-stream")

    if settings.stt_provider != "local":
        try:
            provider = get_stt()
            result = await provider.transcribe(audio, content_type=content_type)
        except STTNotConfigured as e:
            raise HTTPException(status_code=503, detail=str(e)) from None
        except STTError as e:
            raise HTTPException(status_code=502, detail=str(e)) from None
        return TranscriptResponse(text=result.text)

    try:
        async with httpx.AsyncClient(timeout=settings.stt_timeout_sec) as client:
            resp = await client.post(
                f"{settings.stt_url.rstrip('/')}/transcribe",
                content=audio,
                headers={"Content-Type": content_type},
            )
    except httpx.HTTPError as e:
        log.warning("stt.unreachable", error=str(e))
        raise HTTPException(
            status_code=503,
            detail="Распознавание речи сейчас недоступно — наберите команду текстом",
        ) from None
    if resp.status_code != 200:
        raise HTTPException(
            status_code=502 if resp.status_code >= 500 else resp.status_code,
            detail="Не удалось распознать запись — попробуйте ещё раз или наберите текстом",
        )
    return TranscriptResponse(text=str(resp.json().get("text") or "").strip())


# ─── Диалоги ────────────────────────────────────────────────────────────────


@router.get("/ai/conversations", response_model=list[ConversationResponse])
async def list_conversations(
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> list[ConversationResponse]:
    rows = (
        (
            await db.execute(
                select(AiConversation)
                .where(AiConversation.employee_id == principal.employee_id)
                .order_by(AiConversation.updated_at.desc())
                .limit(20)
            )
        )
        .scalars()
        .all()
    )
    return [
        ConversationResponse(id=c.id, title=c.title, updated_at=c.updated_at.isoformat())
        for c in rows
    ]


@router.get("/ai/conversations/{conversation_id}/messages", response_model=list[MessageResponse])
async def conversation_messages(
    conversation_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> list[MessageResponse]:
    conversation = await db.get(AiConversation, conversation_id)
    if conversation is None or conversation.employee_id != principal.employee_id:
        raise HTTPException(status_code=404, detail="Диалог не найден")
    rows = (
        (
            await db.execute(
                select(AiMessage)
                .where(AiMessage.conversation_id == conversation_id)
                .order_by(AiMessage.created_at, _ROLE_RANK)
            )
        )
        .scalars()
        .all()
    )
    return [
        MessageResponse(
            id=m.id,
            role=m.role,
            kind=m.kind,
            content=m.content,
            sources=m.sources,
            data=await _hydrate(db, m.data),
            created_at=m.created_at.isoformat(),
        )
        for m in rows
    ]


@router.delete("/ai/conversations/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> None:
    conversation = await db.get(AiConversation, conversation_id)
    if conversation is None or conversation.employee_id != principal.employee_id:
        raise HTTPException(status_code=404, detail="Диалог не найден")
    await db.delete(conversation)
    await db.commit()


# ─── Планы ──────────────────────────────────────────────────────────────────


@router.post("/ai/plans/{plan_id}/execute")
async def execute_plan(
    plan_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await enforce_rate_limit(
        bucket="ai:exec", employee_id=str(principal.employee_id), limit=30, window_sec=60
    )
    # FOR UPDATE: два нажатия «Выполнить» не должны создать две задачи.
    plan = await plan_service.load_for_actor(db, plan_id, principal, lock=True)
    try:
        executed = await plan_service.execute(db, plan, principal)
    except plan_service.PlanError as e:
        raise HTTPException(status_code=409, detail=str(e)) from None
    return plan_service.serialize(executed)


@router.post("/ai/plans/{plan_id}/reject")
async def reject_plan(
    plan_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    plan = await plan_service.load_for_actor(db, plan_id, principal)
    if plan.status == "pending":
        plan.status = "rejected"
        await db.commit()
    return plan_service.serialize(plan)


@router.patch("/ai/plans/{plan_id}")
async def patch_plan(
    plan_id: UUID,
    body: plan_service.PlanPatch,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    plan = await plan_service.load_for_actor(db, plan_id, principal)
    ctx = await _ctx(db, principal)
    try:
        updated = await plan_service.apply_patch(ctx, plan, body)
    except plan_service.PlanError as e:
        raise HTTPException(status_code=409, detail=str(e)) from None
    except Exception as e:  # резолв имени сотрудника мог не удаться
        from app.services.assistant.context import Ambiguous, NotFound

        if isinstance(e, (Ambiguous, NotFound)):
            raise HTTPException(status_code=422, detail=str(e)) from None
        raise
    return plan_service.serialize(updated)

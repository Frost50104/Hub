"""AI-помощник API (Ф6, ТЗ §19): RAG-чат по знаниям компании.

ИНВАРИАНТ (план, тест обязателен): retrieval фильтрует чанки по
audience_members — ассистент физически не достаёт контент чужой аудитории
(rag_chunks.audience_id денормализован из search_documents).

Без ключа провайдера — 503 «не настроен» (фронт показывает плашку).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from signaris_auth import Principal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import enforce_rate_limit, get_db, require_auth
from app.models.ai import AiConversation, AiMessage, RagChunk
from app.models.audience import AudienceMember
from app.services.llm import (
    ChatMessage,
    LLMError,
    LLMNotConfigured,
    get_provider,
)
from app.services.org_scope import get_profile

router = APIRouter(tags=["learn-ai"])

TOP_K = 6
HISTORY_LIMIT = 6

SYSTEM_PROMPT = (
    "Ты — AI-помощник платформы обучения. Отвечай на вопросы сотрудников "
    "ТОЛЬКО на основе предоставленного контекста из базы знаний компании. "
    "Если в контексте нет ответа — честно скажи, что в базе знаний этого "
    "нет, и посоветуй обратиться к руководителю. Не выдумывай факты, цены "
    "и регламенты. Отвечай по-русски, кратко и по делу. В конце ответа "
    "перечисли номера использованных источников в формате [1], [2]."
)


class AskBody(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    conversation_id: UUID | None = None


class SourceRef(BaseModel):
    title: str
    url_path: str


class AskResponse(BaseModel):
    conversation_id: UUID
    answer: str
    sources: list[SourceRef]


class ConversationResponse(BaseModel):
    id: UUID
    title: str
    updated_at: str


class MessageResponse(BaseModel):
    id: UUID
    role: str
    content: str
    sources: list[SourceRef] | None
    created_at: str


class StatusResponse(BaseModel):
    configured: bool
    provider: str | None = None


@router.get("/learn/ai/status", response_model=StatusResponse)
async def ai_status(principal: Principal = Depends(require_auth())) -> StatusResponse:
    try:
        provider = get_provider()
        return StatusResponse(configured=True, provider=provider.name)
    except LLMNotConfigured:
        return StatusResponse(configured=False)


async def retrieve_chunks(
    db: AsyncSession,
    *,
    embed_model: str,
    query_vector: list[float],
    profile_id: UUID,
    limit: int = TOP_K,
) -> list[RagChunk]:
    """Топ-K чанков по косинусной близости С ФИЛЬТРОМ аудитории."""
    member_exists = (
        select(AudienceMember.profile_id)
        .where(
            AudienceMember.audience_id == RagChunk.audience_id,
            AudienceMember.profile_id == profile_id,
        )
        .exists()
    )
    stmt = (
        select(RagChunk)
        .where(
            RagChunk.embedding_model == embed_model,
            (RagChunk.audience_id.is_(None)) | member_exists,
        )
        .order_by(RagChunk.embedding.cosine_distance(query_vector))
        .limit(limit)
    )
    return list((await db.execute(stmt)).scalars().all())


def _sources(chunks: list[RagChunk]) -> list[SourceRef]:
    seen: dict[str, SourceRef] = {}
    for chunk in chunks:
        key = f"{chunk.object_type}:{chunk.object_id}"
        if key not in seen:
            seen[key] = SourceRef(title=chunk.title, url_path=chunk.url_path)
    return list(seen.values())


@router.post("/learn/ai/ask", response_model=AskResponse)
async def ask(
    body: AskBody,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> AskResponse:
    await enforce_rate_limit(
        bucket="ai:ask",
        employee_id=str(principal.employee_id),
        limit=20,
        window_sec=60,
    )
    profile = await get_profile(db, principal)
    if profile is None:
        raise HTTPException(status_code=404, detail="Профиль не найден")
    try:
        provider = get_provider()
    except LLMNotConfigured as e:
        raise HTTPException(status_code=503, detail=str(e)) from None

    # Диалог: свой существующий или новый.
    conversation: AiConversation | None = None
    if body.conversation_id is not None:
        conversation = await db.get(AiConversation, body.conversation_id)
        if conversation is None or conversation.profile_id != profile.id:
            raise HTTPException(status_code=404, detail="Диалог не найден")
    if conversation is None:
        conversation = AiConversation(
            tenant_id=principal.tenant_id,
            profile_id=profile.id,
            title=body.question[:80],
        )
        db.add(conversation)
        await db.flush()

    history = (
        (
            await db.execute(
                select(AiMessage)
                .where(AiMessage.conversation_id == conversation.id)
                .order_by(AiMessage.created_at.desc())
                .limit(HISTORY_LIMIT)
            )
        )
        .scalars()
        .all()
    )

    try:
        query_vector = (await provider.embed([body.question]))[0]
        chunks = await retrieve_chunks(
            db,
            embed_model=provider.embed_model,
            query_vector=query_vector,
            profile_id=profile.id,
        )
        context = "\n\n".join(
            f"[{i + 1}] {c.title}\n{c.content}" for i, c in enumerate(chunks)
        ) or "(база знаний пуста)"
        messages = [
            ChatMessage(role="system", content=f"{SYSTEM_PROMPT}\n\nКОНТЕКСТ:\n{context}"),
            *[
                ChatMessage(role=m.role, content=m.content)
                for m in reversed(history)
            ],
            ChatMessage(role="user", content=body.question),
        ]
        answer = await provider.chat(messages)
    except LLMError as e:
        raise HTTPException(status_code=502, detail=f"AI-провайдер недоступен: {e}") from None

    sources = _sources(chunks)
    db.add(
        AiMessage(
            tenant_id=principal.tenant_id,
            conversation_id=conversation.id,
            role="user",
            content=body.question,
        )
    )
    db.add(
        AiMessage(
            tenant_id=principal.tenant_id,
            conversation_id=conversation.id,
            role="assistant",
            content=answer,
            sources=[s.model_dump() for s in sources],
        )
    )
    await db.commit()
    return AskResponse(
        conversation_id=conversation.id, answer=answer, sources=sources
    )


@router.get("/learn/ai/conversations", response_model=list[ConversationResponse])
async def list_conversations(
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> list[ConversationResponse]:
    profile = await get_profile(db, principal)
    if profile is None:
        return []
    rows = (
        (
            await db.execute(
                select(AiConversation)
                .where(AiConversation.profile_id == profile.id)
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


@router.get(
    "/learn/ai/conversations/{conversation_id}/messages",
    response_model=list[MessageResponse],
)
async def conversation_messages(
    conversation_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> list[MessageResponse]:
    profile = await get_profile(db, principal)
    conversation = await db.get(AiConversation, conversation_id)
    if profile is None or conversation is None or conversation.profile_id != profile.id:
        raise HTTPException(status_code=404, detail="Диалог не найден")
    rows = (
        (
            await db.execute(
                select(AiMessage)
                .where(AiMessage.conversation_id == conversation_id)
                .order_by(AiMessage.created_at)
            )
        )
        .scalars()
        .all()
    )
    return [
        MessageResponse(
            id=m.id,
            role=m.role,
            content=m.content,
            sources=[SourceRef(**s) for s in m.sources] if m.sources else None,
            created_at=m.created_at.isoformat(),
        )
        for m in rows
    ]


@router.delete("/learn/ai/conversations/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> None:
    profile = await get_profile(db, principal)
    conversation = await db.get(AiConversation, conversation_id)
    if profile is None or conversation is None or conversation.profile_id != profile.id:
        raise HTTPException(status_code=404, detail="Диалог не найден")
    await db.delete(conversation)
    await db.commit()

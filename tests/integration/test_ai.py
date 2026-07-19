"""Integration-тесты Ф6: RAG-индексация, ИНВАРИАНТ audience-фильтра
retrieval, ask-flow с fake-провайдером."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai import AiMessage, RagChunk
from app.models.audience import Audience, AudienceMember
from app.services.llm.base import ChatMessage
from app.services.rag_indexer import reconcile, reindex_document
from app.services.search_indexer import upsert_document
from tests.integration.test_courses import _mk_member

pytestmark = pytest.mark.integration


class FakeProvider:
    """Детерминированные «эмбеддинги» по hash — без сети."""

    name = "fake"
    embed_model = "fake:test-8d"

    def __init__(self) -> None:
        self.chat_calls: list[list[ChatMessage]] = []

    async def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for text in texts:
            digest = hashlib.sha256(text.encode()).digest()
            out.append([b / 255 for b in digest[:8]])
        return out

    async def chat(self, messages: list[ChatMessage]) -> str:
        self.chat_calls.append(messages)
        return "Ответ по базе знаний [1]."


@pytest.fixture(autouse=True)
def _no_push(monkeypatch):
    from app.services import notify_batch

    monkeypatch.setattr(notify_batch, "_schedule_push_batch", lambda **kw: None)


async def _index_doc(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    provider: FakeProvider,
    *,
    title: str,
    body: str,
    audience_id: uuid.UUID | None = None,
) -> uuid.UUID:
    object_id = uuid.uuid4()
    await upsert_document(
        db,
        tenant_id=tenant_id,
        object_type="library_material",
        object_id=object_id,
        title=title,
        body_text=body,
        audience_id=audience_id,
        published_at=datetime.now(UTC),
        url_path=f"/learn/library?m={object_id}",
    )
    await db.flush()
    from app.models.search_document import SearchDocument

    doc = (
        await db.execute(
            select(SearchDocument).where(SearchDocument.object_id == object_id)
        )
    ).scalar_one()
    await reindex_document(db, provider, doc)
    await db.flush()
    return object_id


async def test_retrieval_filters_by_audience(db: AsyncSession, tenant_id: uuid.UUID):
    """ИНВАРИАНТ Ф6: ассистент не достаёт контент чужой аудитории."""
    from app.api.ai import retrieve_chunks

    provider = FakeProvider()
    _member, profile = await _mk_member(db, tenant_id, email="ai1@t.ru")

    audience = Audience(tenant_id=tenant_id)
    db.add(audience)
    await db.flush()

    public_id = await _index_doc(
        db, tenant_id, provider, title="Общий регламент", body="Открытый текст для всех."
    )
    secret_id = await _index_doc(
        db,
        tenant_id,
        provider,
        title="Регламент управляющих",
        body="Закрытый текст только для аудитории управляющих.",
        audience_id=audience.id,
    )

    qvec = (await provider.embed(["регламент"]))[0]

    # Профиль НЕ в аудитории — секретные чанки не возвращаются.
    chunks = await retrieve_chunks(
        db, embed_model=provider.embed_model, query_vector=qvec, profile_id=profile.id
    )
    ids = {c.object_id for c in chunks}
    assert public_id in ids
    assert secret_id not in ids

    # Добавили в аудиторию — чанки стали видны.
    db.add(
        AudienceMember(
            tenant_id=tenant_id, audience_id=audience.id, profile_id=profile.id
        )
    )
    await db.flush()
    chunks2 = await retrieve_chunks(
        db, embed_model=provider.embed_model, query_vector=qvec, profile_id=profile.id
    )
    ids2 = {c.object_id for c in chunks2}
    assert {public_id, secret_id} <= ids2

    # Чужая embedding-модель отфильтровывается (смена провайдера).
    chunks3 = await retrieve_chunks(
        db, embed_model="other:model", query_vector=qvec, profile_id=profile.id
    )
    assert chunks3 == []


async def test_reconcile_indexes_and_cleans(db: AsyncSession, tenant_id: uuid.UUID):
    provider = FakeProvider()
    object_id = uuid.uuid4()
    await upsert_document(
        db,
        tenant_id=tenant_id,
        object_type="course",
        object_id=object_id,
        title="Курс о сервисе",
        body_text="Гость всегда прав. " * 30,
        published_at=datetime.now(UTC),
        url_path=f"/learn/courses/{object_id}",
    )
    await db.flush()

    stats = await reconcile(db, provider, limit=10)
    assert stats["docs"] >= 1 and stats["chunks"] >= 1
    await db.flush()

    # Повторный reconcile — ничего нового (актуально).
    count_before = (
        await db.execute(
            select(RagChunk).where(RagChunk.object_id == object_id)
        )
    ).scalars().all()
    await reconcile(db, provider, limit=10)
    await db.flush()

    # Документ снят с публикации → чанки-сироты подчищаются.
    from app.services.search_indexer import delete_document

    await delete_document(db, object_type="course", object_id=object_id)
    await db.flush()
    stats3 = await reconcile(db, provider, limit=10)
    assert stats3["orphans_deleted"] >= len(count_before)
    remaining = (
        await db.execute(select(RagChunk).where(RagChunk.object_id == object_id))
    ).scalars().all()
    assert remaining == []


async def test_ask_flow_saves_dialog(
    db: AsyncSession, tenant_id: uuid.UUID, monkeypatch
):
    from app.api import ai as ai_api

    provider = FakeProvider()
    monkeypatch.setattr(ai_api, "get_provider", lambda: provider)

    async def _noop_rate_limit(**kw) -> None:
        return None

    monkeypatch.setattr(ai_api, "enforce_rate_limit", _noop_rate_limit)

    member, _profile = await _mk_member(db, tenant_id, email="ai2@t.ru")
    await _index_doc(
        db, tenant_id, provider, title="Стандарт приветствия", body="Приветствуем за 10 секунд."
    )

    from app.api.ai import AskBody, ask, conversation_messages

    resp = await ask(AskBody(question="Как приветствовать гостя?"), member, db)
    assert resp.answer.startswith("Ответ по базе")
    assert any(s.title == "Стандарт приветствия" for s in resp.sources)

    # Контекст дошёл до модели.
    system = provider.chat_calls[0][0]
    assert "Стандарт приветствия" in system.content

    messages = await conversation_messages(resp.conversation_id, member, db)
    assert [m.role for m in messages] == ["user", "assistant"]
    assert messages[1].sources and messages[1].sources[0].title == "Стандарт приветствия"

    # Второй вопрос в том же диалоге — история растёт.
    resp2 = await ask(
        AskBody(question="А если очередь?", conversation_id=resp.conversation_id),
        member,
        db,
    )
    assert resp2.conversation_id == resp.conversation_id
    saved = (
        await db.execute(
            select(AiMessage).where(AiMessage.conversation_id == resp.conversation_id)
        )
    ).scalars().all()
    assert len(saved) == 4

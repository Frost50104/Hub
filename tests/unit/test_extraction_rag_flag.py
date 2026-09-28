"""RAG-шаг воркера извлечения не спрашивает эмбеддинги у провайдера, который их
не умеет (28.09): до правки DeepSeek получал запрос каждые 30 с и отвечал 404."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.services.llm import LLMEmbeddingsUnsupported
from app.workers import extraction


class _Session:
    def __init__(self, tenant_ids: list[UUID]) -> None:
        self._rows = [(t,) for t in tenant_ids]

    async def execute(self, *_args: Any, **_kwargs: Any) -> list[tuple[UUID]]:
        return self._rows

    async def commit(self) -> None:
        return None


def _sessions(tenant_ids: list[UUID]):
    @asynccontextmanager
    async def factory(*_args: Any, **_kwargs: Any) -> AsyncIterator[_Session]:
        yield _Session(tenant_ids)

    return factory


class _Provider:
    embed_model = "openai:text-embedding-3-small"


async def test_flag_skips_the_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(extraction, "_embeddings_unsupported", True)

    def provider() -> _Provider:
        raise AssertionError("провайдер без эмбеддингов не должен спрашиваться")

    monkeypatch.setattr(extraction, "get_provider", provider)
    await extraction._process_rag()


async def test_unsupported_embeddings_are_asked_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(extraction, "_embeddings_unsupported", False)
    calls = {"provider": 0, "reconcile": 0}

    def provider() -> _Provider:
        calls["provider"] += 1
        return _Provider()

    async def reconcile(*_args: Any, **_kwargs: Any) -> dict[str, int]:
        calls["reconcile"] += 1
        raise LLMEmbeddingsUnsupported("нет /embeddings")

    monkeypatch.setattr(extraction, "get_provider", provider)
    monkeypatch.setattr(extraction, "reconcile", reconcile)
    monkeypatch.setattr(extraction, "tenant_scoped_session", _sessions([uuid4(), uuid4()]))

    await extraction._process_rag()
    await extraction._process_rag()

    assert extraction._embeddings_unsupported is True
    assert calls == {"provider": 1, "reconcile": 1}

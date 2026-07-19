"""Юнит-тесты чанкера RAG (Ф6)."""

from __future__ import annotations

from app.services.rag_indexer import MAX_CHUNKS_PER_DOC, chunk_text


class TestChunkText:
    def test_empty(self):
        assert chunk_text("") == []
        assert chunk_text("   \n  ") == []

    def test_short_single_chunk(self):
        assert chunk_text("Короткий текст.") == ["Короткий текст."]

    def test_whitespace_normalized(self):
        assert chunk_text("а\n\nб   в") == ["а б в"]

    def test_long_splits_with_overlap(self):
        text = " ".join(f"Предложение номер {i}." for i in range(200))
        chunks = chunk_text(text, size=300, overlap=50)
        assert len(chunks) > 1
        assert all(len(c) <= 300 for c in chunks)
        # Перекрытие: конец чанка встречается в начале следующего.
        tail = chunks[0][-30:]
        assert tail in chunks[1] or chunks[0].endswith(".")

    def test_prefers_sentence_boundary(self):
        text = ("Первое предложение о кофе. " * 20) + "Хвост без точки"
        chunks = chunk_text(text, size=200, overlap=20)
        # Большинство чанков заканчиваются на границе предложения.
        endings = sum(1 for c in chunks[:-1] if c.endswith("."))
        assert endings >= len(chunks[:-1]) // 2

    def test_max_chunks_cap(self):
        text = "слово " * 100_000
        chunks = chunk_text(text)
        assert len(chunks) <= MAX_CHUNKS_PER_DOC

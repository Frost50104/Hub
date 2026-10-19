"""Границы тела массовой отметки «Входящих» — юниты, потому что CI не гоняет
интеграционные тесты, а потолок id зеркалится клиентом."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas.notification import READ_STATE_MAX_IDS, ReadStateUpdate

_CLIENT_MIRROR = Path(__file__).resolve().parents[2] / "web" / "src" / "lib" / "inboxSelection.ts"


def test_read_state_requires_at_least_one_id():
    with pytest.raises(ValidationError):
        ReadStateUpdate(ids=[], is_read=True)


def test_read_state_caps_ids_at_the_mirror_constant():
    ReadStateUpdate(ids=list(range(READ_STATE_MAX_IDS)), is_read=False)
    with pytest.raises(ValidationError):
        ReadStateUpdate(ids=list(range(READ_STATE_MAX_IDS + 1)), is_read=False)


def test_client_chunk_size_mirrors_server_cap():
    """`lib/inboxSelection.ts::READ_STATE_MAX` режет выбор чанками под этот
    потолок; разъехавшиеся значения — 422 на большом выборе."""
    source = _CLIENT_MIRROR.read_text(encoding="utf-8")
    match = re.search(r"export const READ_STATE_MAX = (\d+)", source)
    assert match is not None, "константа READ_STATE_MAX пропала из inboxSelection.ts"
    assert int(match.group(1)) == READ_STATE_MAX_IDS

"""Какая архивная карточка держит адрес от синка штата (`archived_skip`).

Держит, пока учётка за ней может быть жива: иначе pull заводил бы заново
человека, которого убрали в архив руками. Учётку удалили в auth — ящик
свободен, новая учётка на нём получает новую карточку (решение владельца 01.09).
"""

from __future__ import annotations

import pytest

from app.services.employee_profiles import archived_twin_blocks_sync


@pytest.mark.parametrize("reason", ["manual", "auth_deactivated", "auto_inactivity", None])
def test_twin_whose_account_may_be_alive_holds_the_mailbox(reason: str | None) -> None:
    assert archived_twin_blocks_sync(reason) is True


def test_deleted_account_frees_the_mailbox() -> None:
    assert archived_twin_blocks_sync("auth_deleted") is False

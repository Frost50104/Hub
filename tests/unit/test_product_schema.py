"""Замок на решение «публикацию продукта делаем вторым запросом».

Тест юнитовый намеренно: интеграционные в CI не бегут
(`pytest -m "not integration"`), а сторожить контракт нужно на каждом прогоне.
"""

from __future__ import annotations

from app.schemas.product import ProductUpsert


def test_upsert_has_no_status_field():
    """`ProductUpsert` — ОБЩАЯ схема create и PATCH, а `_apply_upsert` кладёт
    поля слепым setattr. Появись здесь `status`, автор опубликовал бы карточку
    через PATCH мимо матрицы lifecycle: без прав, без published_at, без audit
    и без переиндексации в search_documents.
    """
    assert "status" not in ProductUpsert.model_fields

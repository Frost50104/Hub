"""Длительность видео на сервере — media_files.duration_sec

Revision ID: 0043
Revises: 0042
Create Date: 2026-08-24

Гейт досмотра делит просмотренное на длительность, а знала её до сих пор только
одна сторона — браузер. Клиентское число ломает гейт в обе стороны: занижение
открывает его раньше времени, а завышение всего в 1,12 раза делает порог 90%
физически недостижимым (посмотреть больше, чем длится ролик, нельзя), и человек
получает вечное «Досмотрите обязательное видео». Файл под media_id неизменяем
(загрузка всегда создаёт новую строку), значит длительность — константа, и
сервер обязан читать её сам: `learn_media.mp4_duration_seconds` (moov→mvhd).

Колонка nullable и гейт fail-open: NULL (не видео, не mp4, битый moov)
означает откат на прежнее поведение — значение из block_state. Поэтому миграция
аддитивна и безопасна в окне деплоя (alembic до рестарта).

Бэкфилл существующих файлов НЕ здесь, а отдельным job'ом
`python -m app.jobs.backfill_media_duration`: он читает файлы с диска, и
недоступный файл не должен валить `alembic upgrade`.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0043"
down_revision: str | None = "0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "media_files", sa.Column("duration_sec", sa.Float(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("media_files", "duration_sec")

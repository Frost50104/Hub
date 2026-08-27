"""Бейдж проекта: раскладка на диске, подпись адреса, whitelist типов.

Вместо двухбуквенного квадрата проект может нести эмодзи или картинку. Эмодзи
живёт строкой в `projects.badge_emoji` и никакого хранилища не требует; здесь —
всё про картинку.

Адрес подписан БЕЗ срока (`sign_immutable`), и это осознанно отличается от
learn-медиа: у `<img>` бейджа нет причины менять `src`, а `issue_token`
переиздаёт URL каждый час — то есть перекачка вместо 304 и мигание пустого
квадрата разом по всему списку проектов. Версию адреса даёт сам `storage_key`:
на каждую заливку в нём свежий uuid, поэтому новая картинка = новый URL, а
старая подпись перестаёт верифицироваться.

Плата за бессрочность: утёкший адрес живёт, пока жив файл. Для квадрата 40×40
это принято — подпись здесь анти-энумерация, а не секрет; снятый бейдж отдаёт
404, заменённый — новый адрес.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from app.models.project import Project
from app.services.learn_media import sign_immutable, verify_immutable

# png/jpeg/webp и только они. `gif` — нет: анимация в 22-пиксельном квадрате
# сайдбара это шум, а паузы у неё нет. `svg` — нет по уже записанной причине
# (XML со скриптом, stored-XSS: см. ALLOWED_MIME в app/services/attachments.py),
# и здесь она СТРОЖЕ, чем у вложений: бейдж отдаётся inline, а вложение —
# `Content-Disposition: attachment`. `heic/heif` — нет: браузеры их не
# декодируют, а сервер картинку не перекодирует.
#
# Список зеркалит CHECK `ck_projects_badge_mime` (миграция 0049) — менять
# ПАРОЙ, иначе ручка отдаст 201, а Postgres откатит транзакцию.
BADGE_MIME_EXT: dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}

# Бейдж рисуется 22 / 36 / 40 / 64 CSS-px, то есть максимум ~190 физических
# пикселей при DPR 3 — честному PNG хватает 20–30 КБ. 512 КБ это ~17-кратный
# запас: пропускает несжатый квадрат 512×512 и громко отвергает снимок прямо с
# камеры (3–8 МБ), который иначе поехал бы в каждый рендер списка. Сервер
# картинку НЕ ресайзит (Pillow в зависимостях нет, и тащить декодер чужих
# картинок в API-процесс на 2-гигабайтный VPS ради бейджа не стоит) — ресайз
# делает клиент, сервер лишь ставит потолок.
BADGE_MAX_BYTES: int = 512 * 1024


def storage_key_for_badge(tenant_id: UUID, project_id: UUID, mime: str) -> str:
    """`{tenant}/projects/{project_id}/{uuid}.{ext}` — относительно attachments_root.

    Свежий uuid на КАЖДУЮ заливку: подпись считается от ключа, поэтому новый
    файл автоматически получает новый адрес, а прежние байты не остаются под
    тем же URL в кэше браузера.

    Каталог `projects` не может столкнуться с каталогом задачи
    (`{tenant}/{task_id}/…`): `task_id` — UUID, а не слово.
    """
    return f"{tenant_id}/projects/{project_id}/{uuid4().hex}{BADGE_MIME_EXT[mime]}"


def _sign_key(project_id: UUID, storage_key: str) -> str:
    """Пространство подписи: подпись медиа нельзя предъявить бейджу и наоборот."""
    return f"projectbadge:{project_id}:{storage_key}"


def badge_url(project: Project) -> str | None:
    """Подписанный относительный путь к картинке или None (эмодзи/буквы).

    Чистая функция от строки и секрета — БЕЗ обращения к БД. Поэтому её можно
    звать в `_project_to_response` для каждой строки списка проектов, и N+1 не
    появляется.
    """
    if not project.badge_storage_key:
        return None
    sig = sign_immutable(_sign_key(project.id, project.badge_storage_key))
    return f"/api/projects/{project.id}/badge?s={sig}"


def verify_badge_signature(project_id: UUID, storage_key: str, sig: str) -> bool:
    return verify_immutable(_sign_key(project_id, storage_key), sig)

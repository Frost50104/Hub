"""One-shot: импорт учебных материалов из bundle (миграция с ServiceGuru).

Bundle готовится локально (`tools/import_lms/build_bundle.py`) и кладётся
рядом с приложением; здесь только запись в БД и файлы — ни сети, ни парсинга
xlsx. Идёт мимо HTTP API: авторизация в Hub только SSO, токен скрипту взять
неоткуда, а доменные инварианты (валидация контента, lifecycle, реиндекс)
переиспользуются сервисными функциями напрямую.

Идемпотентность: курс считается импортированным, только если он published
(публикация — последний шаг). Прерванный импорт оставляет курс в draft, и
повторный запуск докатывает недостающие уроки/тесты и публикует.

Запуск на VPS от пользователя приложения (файлы должен читать nginx):
    cd /opt/signaris-hub && sudo -u signaris .venv/bin/python \\
        -m app.jobs.import_lms_bundle --bundle ./import-bundle [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import log as log_config
from app.db import tenant_scoped_session
from app.models.course import Course, CourseLesson, MediaFile
from app.models.library import LibraryMaterial, LibrarySection, MaterialVersion
from app.models.product import ProductCard, ProductCategory
from app.models.quiz import Quiz, QuizQuestion
from app.models.search_document import TextExtractionJob
from app.models.shadow import ShadowUser
from app.services import lifecycle
from app.services.attachments import absolute_path
from app.services.audience_resolver import RuleSpec, set_object_audience
from app.services.learn_media import (
    MEDIA_MIME_KINDS,
    check_free_space,
    mp4_has_faststart,
    storage_key_for_media,
)
from app.services.lesson_content import extract_lesson_text, validate_lesson_content
from app.services.library_storage import storage_key_for_version
from app.services.search_indexer import upsert_document

log = structlog.get_logger("jobs.import_lms_bundle")

_EXT_MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".mp4": "video/mp4"}
_MIN_FREE_BYTES = 5 * 1024 * 1024 * 1024  # как media_min_free_bytes по умолчанию


class Importer:
    def __init__(self, bundle: Path, tenant_id: UUID, actor_id: UUID, dry_run: bool) -> None:
        self.bundle = bundle
        self.files = bundle / "files"
        self.tenant_id = tenant_id
        self.actor_id = actor_id
        self.dry_run = dry_run
        self.stats: dict[str, int] = {}
        self.media_cache: dict[str, UUID] = {}

    def bump(self, key: str, delta: int = 1) -> None:
        self.stats[key] = self.stats.get(key, 0) + delta

    # ─── медиа ──────────────────────────────────────────────────────────────

    async def ensure_media(self, db: AsyncSession, filename: str) -> UUID | None:
        """Создать media_files + положить файл. Кэш — на повторные ссылки."""
        if filename in self.media_cache:
            return self.media_cache[filename]
        src = self.files / filename
        if not src.exists():
            log.warning("media.missing", file=filename)
            return None
        mime = _EXT_MIME.get(src.suffix.lower())
        if mime not in MEDIA_MIME_KINDS:
            log.warning("media.mime_rejected", file=filename, mime=mime)
            return None
        if mime == "video/mp4" and not mp4_has_faststart(src):
            log.warning("media.no_faststart", file=filename)
            return None
        if self.dry_run:
            self.bump("медиа")
            return uuid4()

        media = MediaFile(
            id=uuid4(),
            tenant_id=self.tenant_id,
            kind=MEDIA_MIME_KINDS[mime],
            storage_key="",
            file_name=src.name[:255],
            mime=mime,
            size_bytes=0,
            uploaded_by=self.actor_id,
        )
        db.add(media)
        await db.flush()  # id нужен для storage_key
        storage_key, sanitized = storage_key_for_media(self.tenant_id, media.id, src.name)
        dest = absolute_path(storage_key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(src.read_bytes())
        media.storage_key = storage_key
        media.file_name = sanitized
        media.size_bytes = dest.stat().st_size
        self.media_cache[filename] = media.id
        self.bump("медиа")
        return media.id

    async def _resolve_media_refs(self, db: AsyncSession, content: dict) -> dict:
        """Заменить `@file:<имя>` в attrs.mediaId на реальные UUID."""
        text = json.dumps(content, ensure_ascii=False)
        for ref in sorted(set(_iter_file_refs(content))):
            media_id = await self.ensure_media(db, ref)
            if media_id is None:
                return _drop_nodes_with_ref(content, ref)
            text = text.replace(f"@file:{ref}", str(media_id))
        return json.loads(text)

    # ─── курсы ──────────────────────────────────────────────────────────────

    async def import_course(self, db: AsyncSession, payload: dict) -> None:
        title = payload["title"]
        existing = (
            await db.execute(select(Course).where(Course.title == title))
        ).scalar_one_or_none()
        if existing is not None and existing.status == "published":
            log.info("course.skip", title=title)
            self.bump("курсов пропущено")
            return

        course = existing
        if course is None:
            course = Course(
                id=uuid4(),
                tenant_id=self.tenant_id,
                title=title[:255],
                course_type=payload["course_type"],
                progression_mode="sequential",
                position=payload["position"],
                status="draft",
                owner_id=self.actor_id,
                created_by=self.actor_id,
            )
            if not self.dry_run:
                db.add(course)
                await db.flush()
            self.bump("курсов создано")

        done_titles = set()
        if existing is not None and not self.dry_run:
            done_titles = {
                row[0]
                for row in await db.execute(
                    select(CourseLesson.title).where(CourseLesson.course_id == course.id)
                )
            }

        for lesson_payload in payload["lessons"]:
            if lesson_payload["title"] in done_titles:
                continue
            content = await self._resolve_media_refs(db, lesson_payload["content"])
            validate_lesson_content(content)
            lesson = CourseLesson(
                id=uuid4(),
                tenant_id=self.tenant_id,
                course_id=course.id,
                title=lesson_payload["title"][:255],
                position=lesson_payload["position"],
                content_format="blocks",
                content=content,
                unlock_rule="inherit",
                status="published",
            )
            if not self.dry_run:
                db.add(lesson)
                await db.flush()
            self.bump("уроков")
            if quiz_payload := lesson_payload.get("quiz"):
                await self.import_quiz(db, course.id, lesson.id, quiz_payload)

        if final := payload.get("final_quiz"):
            await self.import_quiz(db, course.id, None, final)

        if self.dry_run:
            self.bump("курсов")
            return

        lifecycle.transition(
            db,
            course,
            "published",
            actor_id=self.actor_id,
            role="admin",
            tenant_id=self.tenant_id,
            object_type="course",
            object_label=course.title,
        )
        await db.flush()
        audience_id = None
        if payload.get("org_roles"):
            audience_id, _diff = await set_object_audience(
                db,
                tenant_id=self.tenant_id,
                current_audience_id=course.audience_id,
                is_all=False,
                rules=[RuleSpec(mode="include", org_roles=frozenset(payload["org_roles"]))],
                object_hint=f"course:{course.id}",
            )
            course.audience_id = audience_id
            self.bump("аудиторий")
        await self._reindex_course(db, course)
        self.bump("курсов")

    async def import_quiz(
        self, db: AsyncSession, course_id: UUID, lesson_id: UUID | None, payload: dict
    ) -> None:
        if self.dry_run:
            self.bump("тестов")
            return
        quiz = Quiz(
            id=uuid4(),
            tenant_id=self.tenant_id,
            course_id=course_id,
            lesson_id=lesson_id,
            title=payload["title"][:255],
            status="published",
            pass_score_pct=payload["pass_score_pct"],
            is_required=True,
            created_by=self.actor_id,
        )
        db.add(quiz)
        await db.flush()
        for position, question in enumerate(payload["questions"]):
            media_id = None
            if image := question.get("image"):
                media_id = await self.ensure_media(db, image)
            db.add(
                QuizQuestion(
                    id=uuid4(),
                    tenant_id=self.tenant_id,
                    quiz_id=quiz.id,
                    position=position,
                    qtype=question["qtype"],
                    prompt=question["prompt"][:2000],
                    media_id=media_id,
                    options={"options": question["options"]},
                    answer={"correct": question["correct"]},
                    points=1,
                )
            )
            self.bump("вопросов")
        self.bump("тестов")

    async def _reindex_course(self, db: AsyncSession, course: Course) -> None:
        """Копия логики courses.py::_reindex — API-модуль тянет FastAPI."""
        rows = await db.execute(
            select(CourseLesson.title, CourseLesson.content)
            .where(CourseLesson.course_id == course.id, CourseLesson.status == "published")
            .order_by(CourseLesson.position)
        )
        parts = [course.title]
        for lesson_title, content in rows:
            parts.append(lesson_title)
            if content:
                parts.append(extract_lesson_text(content))
        await upsert_document(
            db,
            tenant_id=self.tenant_id,
            object_type="course",
            object_id=course.id,
            title=course.title,
            url_path=f"/learn/courses/{course.id}",
            snippet=course.description,
            body_text="\n".join(p for p in parts if p)[:50_000],
            audience_id=course.audience_id,
            published_at=course.published_at,
        )

    # ─── библиотека ─────────────────────────────────────────────────────────

    async def ensure_section(self, db: AsyncSession, title: str) -> UUID | None:
        if self.dry_run:
            return None
        existing = (
            await db.execute(select(LibrarySection).where(LibrarySection.title == title))
        ).scalar_one_or_none()
        if existing is not None:
            return existing.id
        position = (
            await db.execute(select(func.coalesce(func.max(LibrarySection.position), -1) + 1))
        ).scalar_one()
        section = LibrarySection(
            id=uuid4(), tenant_id=self.tenant_id, title=title[:255], position=position
        )
        db.add(section)
        await db.flush()
        self.bump("разделов")
        return section.id

    async def import_material(
        self, db: AsyncSession, payload: dict, section_id: UUID | None
    ) -> None:
        title = payload["title"]
        if not self.dry_run:
            existing = (
                await db.execute(select(LibraryMaterial).where(LibraryMaterial.title == title))
            ).scalar_one_or_none()
            if existing is not None:
                self.bump("материалов пропущено")
                return
        src = self.files / payload["file"]
        if not src.exists():
            log.warning("material.missing_file", file=payload["file"])
            return
        if self.dry_run:
            self.bump("материалов")
            return

        material = LibraryMaterial(
            id=uuid4(),
            tenant_id=self.tenant_id,
            section_id=section_id,
            title=title[:255],
            kind="file",
            requires_acknowledgement=False,
            status="draft",
            owner_id=self.actor_id,
            created_by=self.actor_id,
        )
        db.add(material)
        await db.flush()
        storage_key, sanitized = storage_key_for_version(
            self.tenant_id, material.id, 1, payload["file_name"]
        )
        dest = absolute_path(storage_key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(src.read_bytes())
        db.add(
            MaterialVersion(
                id=uuid4(),
                tenant_id=self.tenant_id,
                material_id=material.id,
                version_no=1,
                storage_key=storage_key,
                file_name=sanitized,
                mime=payload["mime"],
                size_bytes=dest.stat().st_size,
                uploaded_by=self.actor_id,
            )
        )
        material.current_version_no = 1
        lifecycle.transition(
            db,
            material,
            "published",
            actor_id=self.actor_id,
            role="admin",
            tenant_id=self.tenant_id,
            object_type="library_material",
            object_label=material.title,
        )
        await db.flush()
        await upsert_document(
            db,
            tenant_id=self.tenant_id,
            object_type="library_material",
            object_id=material.id,
            title=material.title,
            url_path=f"/learn/library?m={material.id}",
            snippet=material.description,
            audience_id=material.audience_id,
            published_at=material.published_at,
        )
        # body_text допишет extraction-воркер (для pdf/docx/text).
        db.add(
            TextExtractionJob(
                tenant_id=self.tenant_id,
                object_type="library_material",
                object_id=material.id,
                storage_key=storage_key,
                mime=payload["mime"],
                status="pending",
            )
        )
        self.bump("материалов")

    # ─── ассортимент ────────────────────────────────────────────────────────

    async def ensure_category(self, db: AsyncSession, title: str) -> UUID | None:
        if self.dry_run:
            return None
        existing = (
            await db.execute(select(ProductCategory).where(ProductCategory.title == title))
        ).scalar_one_or_none()
        if existing is not None:
            return existing.id
        position = (
            await db.execute(select(func.coalesce(func.max(ProductCategory.position), -1) + 1))
        ).scalar_one()
        category = ProductCategory(
            id=uuid4(), tenant_id=self.tenant_id, title=title[:255], position=position
        )
        db.add(category)
        await db.flush()
        self.bump("категорий")
        return category.id

    async def _product_photos(self, db: AsyncSession, payload: dict) -> list[dict]:
        """photos-массив карточки: [{"media_id": "<uuid>"}] (миниатюры меню)."""
        if not payload.get("photo"):
            return []
        media_id = await self.ensure_media(db, payload["photo"])
        return [{"media_id": str(media_id)}] if media_id else []

    async def import_product(
        self, db: AsyncSession, payload: dict, category_id: UUID | None
    ) -> None:
        if self.dry_run:
            self.bump("карточек")
            return
        existing = (
            await db.execute(select(ProductCard).where(ProductCard.title == payload["title"]))
        ).scalar_one_or_none()
        if existing is not None:
            # Докат фото к карточке, созданной прошлым прогоном без него.
            if not existing.photos and payload.get("photo"):
                photos = await self._product_photos(db, payload)
                if photos:
                    existing.photos = photos
                    self.bump("фото добавлено")
            else:
                self.bump("карточек пропущено")
            return
        card = ProductCard(
            id=uuid4(),
            tenant_id=self.tenant_id,
            category_id=category_id,
            title=payload["title"][:255],
            description=payload["description"] or None,
            composition=payload["composition"] or None,
            photos=await self._product_photos(db, payload),
            status="draft",
            owner_id=self.actor_id,
            created_by=self.actor_id,
        )
        db.add(card)
        await db.flush()
        lifecycle.transition(
            db,
            card,
            "published",
            actor_id=self.actor_id,
            role="admin",
            tenant_id=self.tenant_id,
            object_type="product",
            object_label=card.title,
        )
        await db.flush()
        await upsert_document(
            db,
            tenant_id=self.tenant_id,
            object_type="product",
            object_id=card.id,
            title=card.title,
            url_path=f"/learn/products?p={card.id}",
            snippet=card.description,
            body_text=card.composition,
            audience_id=card.audience_id,
            published_at=card.published_at,
        )
        self.bump("карточек")


def _iter_file_refs(node: Any) -> list[str]:
    out: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "mediaId" and isinstance(value, str) and value.startswith("@file:"):
                out.append(value.removeprefix("@file:"))
            else:
                out.extend(_iter_file_refs(value))
    elif isinstance(node, list):
        for item in node:
            out.extend(_iter_file_refs(item))
    return out


def _drop_nodes_with_ref(content: dict, ref: str) -> dict:
    """Выбросить ноды, чьё медиа не удалось создать (урок остаётся живым)."""

    def clean(node: Any) -> Any:
        if isinstance(node, dict):
            attrs = node.get("attrs") or {}
            if attrs.get("mediaId") == f"@file:{ref}":
                return None
            result = {k: clean(v) for k, v in node.items()}
            return {k: v for k, v in result.items() if v is not None}
        if isinstance(node, list):
            return [c for c in (clean(i) for i in node) if c is not None]
        return node

    return clean(content)


async def _find_tenant_and_actor(slug: str, actor_email: str | None) -> tuple[UUID, UUID]:
    from sqlalchemy import text as sa_text

    async with tenant_scoped_session(None, bypass_rls=True) as scan:
        row = (
            await scan.execute(
                sa_text("SELECT id FROM shadow_tenants WHERE slug = :slug"), {"slug": slug}
            )
        ).first()
        if row is None:
            raise SystemExit(f"tenant «{slug}» не найден в shadow_tenants")
        tenant_id = row[0]
        stmt = select(ShadowUser.employee_id, ShadowUser.email).where(
            ShadowUser.tenant_id == tenant_id, ShadowUser.deleted_at.is_(None)
        )
        if actor_email:
            stmt = stmt.where(func.lower(ShadowUser.email) == actor_email.lower())
        actor = (await scan.execute(stmt.limit(1))).first()
        if actor is None:
            raise SystemExit("не найден актор (shadow_users) для tenant'а")
        log.info("import.actor", email=actor[1])
        return tenant_id, actor[0]


async def main() -> int:
    log_config.configure()
    parser = argparse.ArgumentParser(description="Импорт учебных материалов из bundle")
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--tenant-slug", default="uppetit")
    parser.add_argument("--actor-email", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    manifest_path = args.bundle / "manifest.json"
    if not manifest_path.exists():
        raise SystemExit(f"manifest не найден: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    free = check_free_space()
    if free < _MIN_FREE_BYTES:
        raise SystemExit(f"мало места на диске: {free / 1024**3:.1f} ГБ")

    tenant_id, actor_id = await _find_tenant_and_actor(args.tenant_slug, args.actor_email)
    importer = Importer(args.bundle, tenant_id, actor_id, args.dry_run)

    for course in manifest["courses"]:
        async with tenant_scoped_session(tenant_id) as db:
            try:
                await importer.import_course(db, course)
                if not args.dry_run:
                    await db.commit()
            except Exception:
                await db.rollback()
                log.exception("course.failed", title=course["title"])
                importer.bump("курсов с ошибкой")

    sections: dict[str, UUID | None] = {}
    for material in manifest["library"]:
        async with tenant_scoped_session(tenant_id) as db:
            try:
                name = material["section"]
                if name not in sections:
                    sections[name] = await importer.ensure_section(db, name)
                    if not args.dry_run:
                        await db.commit()
                await importer.import_material(db, material, sections[name])
                if not args.dry_run:
                    await db.commit()
            except Exception:
                await db.rollback()
                log.exception("material.failed", title=material["title"])
                importer.bump("материалов с ошибкой")

    categories: dict[str, UUID | None] = {}
    for product in manifest["products"]:
        async with tenant_scoped_session(tenant_id) as db:
            try:
                name = product["category"]
                if name not in categories:
                    categories[name] = await importer.ensure_category(db, name)
                    if not args.dry_run:
                        await db.commit()
                await importer.import_product(db, product, categories[name])
                if not args.dry_run:
                    await db.commit()
            except Exception:
                await db.rollback()
                log.exception("product.failed", title=product["title"])
                importer.bump("карточек с ошибкой")

    log.info("import.done", dry_run=args.dry_run, **importer.stats)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(asyncio.run(main()))

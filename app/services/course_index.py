"""Поисковый документ урока (`object_type='course_lesson'`, 0066): транскрипты
видео урока → поиск и RAG находят фразу из вебинара.

Почему отдельный тип, а не тело документа `course`: у курса кап 50 000
знаков (`courses._reindex`), часовой вебинар — 60–80 тысяч; и у документа
курса есть `published_at`, а урок-документ его НЕ несёт — иначе каждый урок
попал бы в «Новинки» витрины (`learn_home` берёт всё с `published_at`).

Транскрипт ищется по `media_id` видео из ноды, а если это производный файл
без своей расшифровки (чистовик до перемаппинга, монтаж) — по цепочке
`source_media_id`.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import Course, CourseLesson, MediaFile
from app.models.media import MediaTranscript
from app.services.lesson_content import collect_video_ids
from app.services.search_indexer import delete_document, upsert_document

LESSON_OBJECT_TYPE = "course_lesson"
TEXT_LIMIT = 200_000
_CHAIN_DEPTH = 3


async def transcript_texts(
    db: AsyncSession, media_ids: list[UUID], *, _depth: int = 0
) -> dict[UUID, str]:
    """Текст расшифровки по медиа; у производных без своей — текст источника."""
    if not media_ids:
        return {}
    rows = await db.execute(
        select(MediaTranscript.media_id, MediaTranscript.text).where(
            MediaTranscript.media_id.in_(media_ids)
        )
    )
    found: dict[UUID, str] = {mid: text for mid, text in rows if text}
    missing = [mid for mid in media_ids if mid not in found]
    if not missing or _depth >= _CHAIN_DEPTH:
        return found
    sources = dict(
        (
            await db.execute(
                select(MediaFile.id, MediaFile.source_media_id).where(
                    MediaFile.id.in_(missing), MediaFile.source_media_id.is_not(None)
                )
            )
        ).all()
    )
    if not sources:
        return found
    upstream = await transcript_texts(db, list(set(sources.values())), _depth=_depth + 1)
    for mid, source_id in sources.items():
        if source_id in upstream:
            found[mid] = upstream[source_id]
    return found


async def lesson_body_text(db: AsyncSession, content: dict | None) -> str | None:
    if not content:
        return None
    ids: list[UUID] = []
    for raw in collect_video_ids(content):
        mid = UUID(raw)
        if mid not in ids:
            ids.append(mid)
    texts = await transcript_texts(db, ids)
    parts = [texts[mid] for mid in ids if texts.get(mid)]
    return "\n".join(parts)[:TEXT_LIMIT] or None


async def reindex_lesson(db: AsyncSession, course: Course, lesson: CourseLesson) -> bool:
    """Документ есть ТОЛЬКО у опубликованного урока опубликованного курса с
    непустым транскриптом; иначе удаляется. → есть ли документ."""
    if (
        course.status == "published"
        and lesson.status == "published"
        and lesson.content_format == "blocks"
        and lesson.content
    ):
        body = await lesson_body_text(db, lesson.content)
        if body:
            await upsert_document(
                db,
                tenant_id=course.tenant_id,
                object_type=LESSON_OBJECT_TYPE,
                object_id=lesson.id,
                title=f"{course.title} · {lesson.title}"[:512],
                snippet=None,
                body_text=body,
                audience_id=course.audience_id,
                # НЕ published_at курса: урок не должен всплывать в «Новинках».
                published_at=None,
                url_path=f"/learn/lessons/{lesson.id}",
            )
            return True
    await delete_document(db, object_type=LESSON_OBJECT_TYPE, object_id=lesson.id)
    return False


async def reindex_course_lessons(db: AsyncSession, course: Course) -> int:
    lessons = (
        (await db.execute(select(CourseLesson).where(CourseLesson.course_id == course.id)))
        .scalars()
        .all()
    )
    indexed = 0
    for lesson in lessons:
        if await reindex_lesson(db, course, lesson):
            indexed += 1
    return indexed


def lessons_referencing_media_stmt(media_id: UUID):
    """Уроки, в контенте которых есть нода с этим `mediaId` (jsonpath по всему
    дереву, прецедент `courses.py` для опросов)."""
    return (
        select(CourseLesson, Course)
        .join(Course, Course.id == CourseLesson.course_id)
        .where(
            func.jsonb_path_exists(
                CourseLesson.content,
                literal_column("'$.** ? (@.mediaId == $id)'::jsonpath"),
                func.jsonb_build_object("id", str(media_id)),
            )
        )
    )


async def reindex_lessons_for_media(db: AsyncSession, media_id: UUID) -> int:
    """После расшифровки: переиндексировать уроки, где это видео стоит."""
    rows = (await db.execute(lessons_referencing_media_stmt(media_id))).all()
    indexed = 0
    for lesson, course in rows:
        if await reindex_lesson(db, course, lesson):
            indexed += 1
    return indexed

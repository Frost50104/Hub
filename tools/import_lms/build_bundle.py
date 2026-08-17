"""Сборка bundle для импорта: LMS/ (выгрузка ServiceGuru) → import_bundle/.

Bundle самодостаточен: `manifest.json` (курсы, уроки, тесты, библиотека,
ассортимент) + `files/` (медиа и документы). Импортёр на VPS читает только
его — ни xlsx-разбора, ни сети там нет.

Запуск:  .venv/bin/python -m tools.import_lms.build_bundle
"""

from __future__ import annotations

import json
import shutil
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.services.lesson_content import validate_lesson_content
from app.services.rich_content import RichContentError
from tools.import_lms import mapping as M
from tools.import_lms.extract_xlsx import read_lessons, read_menu, read_quizzes
from tools.import_lms.fetch_videos import fetch_youtube, md5_of, prepare_local_video
from tools.import_lms.quill_to_richdoc import html_to_plain, quill_to_nodes

SRC = Path("LMS")
OUT = Path("import_bundle")
FILES = OUT / "files"

# Библиотека принимает не всё: mp4 идут отдельным курсом «Видеоинструкции»,
# zip разворачиваем (внутри — pdf).
LIBRARY_EXT_MIME = {
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".csv": "text/csv",
}


@dataclass
class Report:
    notes: list[str] = field(default_factory=list)
    counters: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    def note(self, text: str) -> None:
        self.notes.append(text)

    def bump(self, key: str, delta: int = 1) -> None:
        self.counters[key] += delta


def _store_bytes(data: bytes, prefix: str, suffix: str) -> str:
    """Положить файл в bundle под именем-хэшем, вернуть имя."""
    digest = __import__("hashlib").md5(data).hexdigest()  # noqa: S324
    name = f"{prefix}_{digest[:16]}{suffix}"
    path = FILES / name
    if not path.exists():
        path.write_bytes(data)
    return name


def _lesson_nodes(rows, media_names: dict[str, str], report: Report) -> list[dict]:
    """Строки листа-урока → ноды RichDoc (обложка первой, если есть файл)."""
    nodes: list[dict] = []
    for row in rows:
        if row.kind == "Глава":
            title = row.content.strip()
            if title:
                nodes.append(
                    {"type": "heading", "attrs": {"level": 2},
                     "content": [{"type": "text", "text": title[:500]}]}
                )
        elif row.kind == "Текст":
            nodes.extend(quill_to_nodes(row.content))
        elif row.kind in ("Изображение", "Изображение урока"):
            if not row.image_md5:
                report.bump("картинок без файла")
                continue
            attrs: dict[str, Any] = {"mediaId": f"@file:{media_names[row.image_md5]}"}
            if row.caption:
                attrs["caption"] = row.caption[:500]
            nodes.append({"type": "figure", "attrs": attrs})
        elif row.kind == "Видео":
            url = row.content.strip()
            local = media_names.get(f"yt:{url}")
            if local:
                nodes.append({"type": "video", "attrs": {"mediaId": f"@file:{local}"}})
            else:
                nodes.append(
                    {
                        "type": "paragraph",
                        "content": [
                            {"type": "text", "text": "Видео: "},
                            {
                                "type": "text",
                                "text": url,
                                "marks": [{"type": "link", "attrs": {"href": url}}],
                            },
                        ],
                    }
                )
                report.bump("видео осталось ссылкой")
        elif row.kind == "Загруженное видео":
            # presigned-ссылки ServiceGuru протухли через 10 минут после выгрузки.
            nodes.append(
                {
                    "type": "callout",
                    "attrs": {"kind": "important"},
                    "content": [
                        {"type": "paragraph",
                         "content": [{"type": "text", "text": M.LOST_VIDEO_NOTE}]}
                    ],
                }
            )
            report.bump("видео требует дозагрузки")
    return nodes


def _quiz_payload(quiz, title: str, media_names: dict[str, str]) -> dict:
    n = len(quiz.questions)
    # Порог 80% на 2-3 вопросах требует безошибочности — смягчаем для малых.
    pass_pct = min(80, (n - 1) * 100 // n) if n else 80
    return {
        "title": title,
        "pass_score_pct": max(pass_pct, 50),
        "questions": [
            {
                "prompt": q.prompt[:2000],
                "qtype": q.qtype,
                "options": q.options,
                "correct": q.correct,
                # Имя файла в bundle (не md5!) — импортёр читает files/<image>.
                "image": media_names.get(q.image_md5) if q.image_md5 else None,
            }
            for q in quiz.questions
        ],
    }


def build_courses(report: Report) -> list[dict]:
    lessons_dir = SRC / "Уроки и тесты"
    media_blobs: dict[str, bytes] = {}
    courses: list[dict] = []

    for slug, (title, course_type, org_roles, position) in M.COURSES.items():
        lessons_file = lessons_dir / f"{slug}_lessons_export.xlsx"
        if not lessons_file.exists():
            report.note(f"нет файла уроков: {slug}")
            continue
        sheets = read_lessons(lessons_file, media_blobs)
        media_names = {md5: _store_bytes(blob, "img", ".jpg") for md5, blob in media_blobs.items()}

        # YouTube-видео курса (скачиваются один раз, кэш в files/).
        for sheet in sheets:
            for row in sheet.rows:
                if row.kind != "Видео":
                    continue
                url = row.content.strip()
                vid = url.rsplit("/", 1)[-1].split("?")[0]
                path, note = fetch_youtube(vid, FILES)
                if path:
                    media_names[f"yt:{url}"] = path.name
                else:
                    report.note(f"YouTube не скачался ({slug}): {url} — {note}")

        quiz_file = lessons_dir / f"{slug}_surveys_export.xlsx"
        quizzes = read_quizzes(quiz_file, media_blobs) if quiz_file.exists() else []
        # Картинки вопросов появились в media_blobs только сейчас — досохраняем.
        for md5, blob in media_blobs.items():
            media_names.setdefault(md5, _store_bytes(blob, "img", ".jpg"))

        by_lesson: dict[str, Any] = {}
        finals: list[Any] = []
        for quiz in quizzes:
            key = (slug, quiz.title)
            if key in M.SKIP_QUIZZES or not quiz.questions:
                report.bump("тестов пропущено (пустые)")
                continue
            if key in M.FINAL_QUIZZES:
                finals.append(quiz)
            elif target := M.QUIZ_TO_LESSON.get(key):
                by_lesson[target] = quiz
            else:
                finals.append(quiz)
                report.note(f"тест без привязки → итоговый ({slug}): «{quiz.title}»")

        lessons_payload: list[dict] = []
        for pos, sheet in enumerate(sheets):
            nodes = _lesson_nodes(sheet.rows, media_names, report)
            if not nodes:
                report.note(f"пустой урок пропущен ({slug}): «{sheet.title}»")
                continue
            doc = {"schema": 1, "doc": {"type": "doc", "content": nodes}}
            try:
                validate_lesson_content(_with_placeholder_media(doc))
            except RichContentError as exc:
                report.note(f"урок не прошёл валидатор ({slug}/{sheet.title}): {exc}")
                continue
            lesson: dict[str, Any] = {
                "title": M.full_title(sheet.title)[:255],
                "position": pos,
                "content": doc,
            }
            if quiz := by_lesson.get(sheet.title):
                lesson["quiz"] = _quiz_payload(quiz, M.full_title(quiz.title)[:255], media_names)
                report.bump("тестов к урокам")
            lessons_payload.append(lesson)
            report.bump("уроков")

        course: dict[str, Any] = {
            "slug": slug,
            "title": title,
            "course_type": course_type,
            "position": position,
            "org_roles": sorted(org_roles) if org_roles else None,
            "lessons": lessons_payload,
        }
        if finals:
            merged = finals[0]
            for extra in finals[1:]:
                merged.questions.extend(extra.questions)
            course["final_quiz"] = _quiz_payload(merged, "Итоговый тест", media_names)
            report.bump("итоговых тестов")
        courses.append(course)
        report.bump("курсов")

    # Медиа тестов: картинки вопросов уже в media_blobs → сохранить файлы.
    for blob in media_blobs.values():
        _store_bytes(blob, "img", ".jpg")
    return courses


def _with_placeholder_media(doc: dict) -> dict:
    """Заменить `@file:`-ссылки на валидные UUID — только для проверки схемы."""
    placeholder = "00000000-0000-0000-0000-000000000000"
    text = json.dumps(doc, ensure_ascii=False)
    import re

    text = re.sub(r'"@file:[^"]+"', f'"{placeholder}"', text)
    return json.loads(text)


def build_video_course(report: Report) -> dict | None:
    """Курс «Видеоинструкции»: mp4 из «Инструкции/» (в библиотеку они не идут)."""
    lessons: list[dict] = []
    seen: dict[str, str] = {}
    for src in sorted((SRC / "Инструкции").glob("*.mp4")):
        digest = md5_of(src)
        if digest in seen:
            report.note(f"дубль видео пропущен: {src.name} == {seen[digest]}")
            continue
        seen[digest] = src.name
        path, note = prepare_local_video(src, FILES)
        if not path:
            report.note(f"видео не готово ({src.name}): {note}")
            continue
        lessons.append(
            {
                "title": M.file_title(src.name)[:255],
                "position": len(lessons),
                "content": {
                    "schema": 1,
                    "doc": {
                        "type": "doc",
                        "content": [{"type": "video", "attrs": {"mediaId": f"@file:{path.name}"}}],
                    },
                },
            }
        )
        report.bump("видеоуроков")
    if not lessons:
        return None
    title, course_type, org_roles, position = M.VIDEO_COURSE
    return {
        "slug": M.VIDEO_COURSE_SLUG,
        "title": title,
        "course_type": course_type,
        "position": position,
        "org_roles": org_roles,
        "lessons": lessons,
    }


def build_library(report: Report) -> list[dict]:
    materials: list[dict] = []
    for src in sorted((SRC / "Инструкции").iterdir()):
        if not src.is_file() or src.name in M.SKIP_FILES:
            continue
        suffix = src.suffix.lower()
        if suffix == ".mp4":
            continue  # уходит в курс «Видеоинструкции»
        if suffix == ".zip":
            with zipfile.ZipFile(src) as zf:
                for inner in zf.namelist():
                    inner_suffix = Path(inner).suffix.lower()
                    if inner_suffix not in LIBRARY_EXT_MIME:
                        continue
                    data = zf.read(inner)
                    name = _store_bytes(data, "doc", inner_suffix)
                    materials.append(
                        {
                            "section": M.section_for_file(src.name),
                            "title": M.file_title(src.name)[:255],
                            "file": name,
                            "file_name": Path(inner).name,
                            "mime": LIBRARY_EXT_MIME[inner_suffix],
                        }
                    )
                    report.bump("материалов")
            continue
        mime = LIBRARY_EXT_MIME.get(suffix)
        if not mime:
            report.note(f"формат не поддержан библиотекой: {src.name}")
            continue
        name = _store_bytes(src.read_bytes(), "doc", suffix)
        materials.append(
            {
                "section": M.section_for_file(src.name),
                "title": M.file_title(src.name)[:255],
                "file": name,
                "file_name": src.name,
                "mime": mime,
            }
        )
        report.bump("материалов")
    return materials


def build_products(report: Report) -> list[dict]:
    menu_files = list((SRC / "Ассортимент").glob("*.xlsx"))
    if not menu_files:
        return []
    photos: dict[str, bytes] = {}
    items = read_menu(menu_files[0], photos)
    photo_names = {md5: _store_bytes(blob, "menu", ".jpg") for md5, blob in photos.items()}
    out: list[dict] = []
    for item in items:
        category = M.MENU_CATEGORY_BY_PATH.get(item["path"]) or item["category"] or "Прочее"
        photo = photo_names.get(item["photo_md5"]) if item.get("photo_md5") else None
        if photo:
            report.bump("фото ассортимента")
        else:
            report.bump("карточек без фото")
        out.append(
            {
                "category": category,
                "title": item["title"][:255],
                "description": html_to_plain(item["description_html"])[:10000],
                "composition": item["composition"][:10000],
                "photo": photo,
            }
        )
        report.bump("карточек ассортимента")
    return out


def main() -> int:
    FILES.mkdir(parents=True, exist_ok=True)
    report = Report()

    courses = build_courses(report)
    if video_course := build_video_course(report):
        courses.append(video_course)
    manifest = {
        "version": 1,
        "courses": courses,
        "library": build_library(report),
        "products": build_products(report),
    }
    (OUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    report_path = OUT / "report.txt"
    lines = [f"{k}: {v}" for k, v in sorted(report.counters.items())]
    lines += ["", "ТРЕБУЕТ ВНИМАНИЯ:", *report.notes]
    report_path.write_text("\n".join(lines), encoding="utf-8")

    total_bytes = sum(f.stat().st_size for f in FILES.iterdir())
    print("\n".join(lines))
    print(f"\nфайлов: {len(list(FILES.iterdir()))}, объём: {total_bytes / 1024 / 1024:.0f} МБ")
    print(f"manifest: {OUT / 'manifest.json'}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


def _unused() -> None:  # pragma: no cover
    shutil.rmtree(OUT, ignore_errors=True)

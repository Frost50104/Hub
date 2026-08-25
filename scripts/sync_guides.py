"""Забрать инструкции из `Hub Instructions/` в `guides/` и проверить их.

Инструкции присылает Claude Design, и присылает часто — каждая перезаливка
требует одних и тех же действий: скопировать под фиксированными именами
(`employee.html` / `admin.html`; backend-rsync идёт без `--delete`, и
переименование оставило бы мусор на сервере), убедиться, что файл переживёт
CSP нашей локации `/_guides/`, и вернуть неприметный скроллбар как в сайдбаре
Hub.

Про CSP. Локация отдаёт инструкции с
`script-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'none'`,
поэтому файл обязан быть самодостаточным: никакого `eval`/`new Function`
(рантайм, компилирующий шаблоны из строк, молча теряет поиск и лайтбокс),
никаких `blob:`-URL, никакой сети и никаких соседних файлов. Одна из присланных
сборок нарушала это всё сразу — проверка здесь, чтобы такое не уехало на прод
незамеченным.

    .venv/bin/python scripts/sync_guides.py            # разбор
    .venv/bin/python scripts/sync_guides.py --apply    # скопировать
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = ROOT / "Hub Instructions"
TARGET_DIR = ROOT / "guides"

# Имя источника → имя в продукте. Второе менять нельзя: по нему настроены
# nginx-локация и `services/guides.py::GUIDE_FILES`.
FILES = {
    "Signaris Hub - инструкция сотрудника.html": "employee.html",
    "Signaris Hub - инструкция администратора.html": "admin.html",
}

# Запрещено CSP локации `/_guides/` (см. ops/nginx/*.conf).
FORBIDDEN = ("new Function", "eval(", "createObjectURL", "XMLHttpRequest", "serviceWorker")

# Скроллбар как в сайдбаре Hub (`web/src/styles/brand.css`): тонкий ползунок,
# прозрачный трек. Цвет — `--text3` тёмной темы, он же `--sig-mid` в токенах
# инструкции. Дописывается сюда, а не просится у дизайна: правка косметическая,
# а перезаливки частые — пусть переживает каждую.
SCROLLBAR_MARK = "/* hub-scrollbar */"
SCROLLBAR_CSS = (
    SCROLLBAR_MARK
    + "*{scrollbar-width:thin;scrollbar-color:rgba(85,85,106,.55) transparent}"
    "*::-webkit-scrollbar{width:6px;height:6px}"
    "*::-webkit-scrollbar-track{background:transparent}"
    "*::-webkit-scrollbar-thumb{background-color:rgba(85,85,106,.55);border-radius:9999px}"
    "*::-webkit-scrollbar-thumb:hover{background-color:rgba(85,85,106,.8)}"
    "*::-webkit-scrollbar-corner{background:transparent}"
)

# Возврат в Hub. В PWA на домашнем экране инструкция открывается ТЕМ ЖЕ окном
# (адрес свой, `target="_blank"` там ничего не меняет), браузерной обвязки нет,
# и выйти из неё нечем. В обычной вкладке ситуация не лучше: вкладка новая, её
# «Назад» пуста. Поэтому ссылка нужна всегда, а не только в standalone.
# Правый нижний угол — единственный, где у инструкции нет своих плавающих
# элементов: сверху полоса прогресса чтения (z-60), слева липкий список
# разделов со «Сбросить», по центру лайтбокс (z-80).
BACK_MARK = "/* hub-back */"
BACK_CSS = (
    BACK_MARK
    + "[data-hub-back]{position:fixed;z-index:90;right:16px;"
    "bottom:max(16px,env(safe-area-inset-bottom));display:inline-flex;align-items:center;"
    "gap:8px;padding:11px 16px;border-radius:999px;"
    "background:var(--sig-white-07,rgba(240,240,245,.07));"
    "border:1px solid var(--sig-white-14,rgba(240,240,245,.14));"
    "color:var(--sig-white,#F0F0F5);font:600 13px/1 var(--font-body,inherit);"
    "text-decoration:none;white-space:nowrap;backdrop-filter:blur(12px);"
    "box-shadow:0 4px 16px rgba(0,0,0,.35)}"
    "[data-hub-back]:hover{background:var(--sig-white-14,rgba(240,240,245,.14))}"
    "[data-hub-back]:focus-visible{outline:2px solid var(--sig-amber,#FFB200);outline-offset:2px}"
    "[data-hub-back] [data-short]{display:none}"
    # На узком экране плавающая кнопка ложится поверх поля «Найти раздел…» —
    # короткая подпись оставляет ему место.
    "@media(max-width:560px){[data-hub-back] [data-full]{display:none}"
    "[data-hub-back] [data-short]{display:inline}}"
    "@media print{[data-hub-back]{display:none}}"
)
BACK_HTML = (
    '<a data-hub-back href="/settings/account" aria-label="Вернуться в Hub">'
    "←<span data-full>Вернуться в Hub</span><span data-short>В Hub</span></a>"
)


def check(html: str) -> list[str]:
    """Что мешает отдавать этот файл под нашей CSP."""
    problems = []
    for pattern in FORBIDDEN:
        if pattern in html:
            problems.append(f"встречается {pattern} — CSP локации это запретит")
    if re.search(r"<script[^>]*\bsrc=", html):
        problems.append("есть <script src=…> — соседних файлов на сервере не будет")
    external = [
        ref
        for ref in re.findall(r'(?:src|href)="([^"]{1,80})"', html)
        if not ref.startswith(("data:", "#"))
    ]
    if external:
        problems.append(f"внешние ссылки: {external[:3]}")
    # fetch() ищем отдельно: строка «fetch(» встречается и в тексте инструкции.
    if re.search(r"\bfetch\s*\(", html):
        problems.append("вызов fetch() — connect-src 'none' его не пустит")
    if not re.search(r"<title>\s*\S", html):
        problems.append("пустой <title> — он показывается в заголовке вкладки")
    return problems


def _add_css(html: str, mark: str, css: str) -> tuple[str, bool]:
    """Дописать правила в конец первого <style>. Идемпотентно."""
    if mark in html:
        return html, False
    end = html.find("</style>")
    if end == -1:
        return html, False
    return html[:end] + css + html[end:], True


def with_scrollbar(html: str) -> tuple[str, bool]:
    return _add_css(html, SCROLLBAR_MARK, SCROLLBAR_CSS)


def with_back_link(html: str) -> tuple[str, bool]:
    """Плавающая ссылка «Вернуться в Hub» перед </body>."""
    if BACK_MARK in html:
        return html, False
    html, added = _add_css(html, BACK_MARK, BACK_CSS)
    if not added:
        return html, False
    end = html.rfind("</body>")
    if end == -1:
        return html, False
    return html[:end] + BACK_HTML + html[end:], True


def main() -> int:
    parser = argparse.ArgumentParser(description="Синхронизировать инструкции")
    parser.add_argument("--apply", action="store_true", help="записать в guides/")
    args = parser.parse_args()

    failed = False
    for source_name, target_name in FILES.items():
        source = SOURCE_DIR / source_name
        target = TARGET_DIR / target_name
        print(f"\n{source_name} → guides/{target_name}")
        if not source.is_file():
            print("  ОШИБКА: файла нет в «Hub Instructions/»")
            failed = True
            continue

        html = source.read_text(encoding="utf-8")
        problems = check(html)
        for problem in problems:
            print(f"  ✗ {problem}")
        if problems:
            failed = True
            continue

        html, scrollbar_added = with_scrollbar(html)
        html, back_added = with_back_link(html)
        title = (re.search(r"<title>([^<]*)", html) or ["", "?"])[1]
        print(f"  ✓ самодостаточна, {len(html) / 1e6:.1f} МБ, «{title.strip()}»")
        print(f"  {'+ скроллбар как в Hub' if scrollbar_added else '· скроллбар уже был'}")
        print(f"  {'+ ссылка «Вернуться в Hub»' if back_added else '· ссылка возврата уже была'}")

        if args.apply:
            target.write_text(html, encoding="utf-8")
            print("  записано")

    if failed:
        print("\nЕсть замечания — ничего не записано. Формат нужен как в")
        print("docs/DEPLOY.md §«Инструкции по Hub».")
        return 1
    if not args.apply:
        print("\nСухой прогон. Повторите с --apply, чтобы записать.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
